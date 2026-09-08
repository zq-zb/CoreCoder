"""在后台事件循环中运行持久化 MCP Client。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from corecoder.mcp_client import DiscoveredTool, MCPToolCallResult, MCPToolExecutionError, PersistentMCPClient

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


class MCPRuntimeState(str, Enum):
    """MCP Runtime 对外可观察的生命周期状态。"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CLOSING = "closing"
    FAILED = "failed"


class MCPCallOutcome(str, Enum):
    """一次 MCP 工具调用的结构化结果类型。"""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True)
class MCPCallRecord:
    """用于日志、指标和排障的一次工具调用摘要。"""

    tool_name: str
    connection_generation: int
    duration_seconds: float
    outcome: MCPCallOutcome
    error: str | None = None


class MCPToolTimeoutError(TimeoutError):
    """等待 MCP 工具结果超过调用方规定的时间。"""

    def __init__(self, tool_name: str, timeout: float) -> None:
        self.tool_name = tool_name
        self.timeout = timeout
        super().__init__(f"MCP 工具 {tool_name!r} 调用超过 {timeout} 秒仍未返回")


class MCPRuntimeUnhealthyError(RuntimeError):
    """Runtime 的当前 MCP 连接已不可信，需要清理并重新连接。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"MCP Runtime 当前不可用：{reason}；请先 close() 再 connect()")


class MCPRuntimeCloseError(RuntimeError):
    """Runtime 在强制清理期限内仍未完成关闭。"""


class MCPTransportError(RuntimeError):
    """MCP 连接或 Server 进程异常，当前连接不可继续信任。"""

    def __init__(self, tool_name: str, cause: Exception) -> None:
        self.tool_name = tool_name
        self.cause = cause
        super().__init__(f"MCP 工具 {tool_name!r} 发生传输故障：{cause}")


@dataclass(frozen=True)
class _CallToolCommand:
    """主线程发送给 Owner Task 的一次工具调用命令。"""

    name: str
    arguments: dict[str, Any]
    reply: concurrent.futures.Future[MCPToolCallResult]


@dataclass(frozen=True)
class _ListToolsCommand:
    """主线程发送给 Owner Task 的一次工具发现命令。"""

    reply: concurrent.futures.Future[list[DiscoveredTool]]


class MCPRuntime:
    """为同步 Agent 提供一个固定的后台 asyncio 事件循环。"""

    def __init__(self) -> None:
        # MCP 的连接、调用和关闭都必须在这个固定事件循环中完成。
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: PersistentMCPClient | None = None
        self._owner_future: concurrent.futures.Future[None] | None = None
        self._commands: asyncio.Queue[_CallToolCommand | _ListToolsCommand | None] | None = None
        self._unhealthy_reason: str | None = None
        self._state = MCPRuntimeState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._connection_generation = 0
        self._call_history: deque[MCPCallRecord] = deque(maxlen=100)
        self._history_lock = threading.Lock()
        self._discovered_tools: dict[str, DiscoveredTool] = {}

        # 主线程通过这个信号判断后台事件循环是否已经准备完成。
        self._started = threading.Event()
        self._client_ready = threading.Event()
        # 无论优雅关闭还是未来的强制取消，都由 Owner Task 在真正完成
        # client.close() 后设置，主线程据此确认底层资源已经清理完毕。
        self._client_closed = threading.Event()

    def _run_event_loop(self) -> None:
        """后台线程入口：创建事件循环，并持续等待异步任务。"""

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        logger.info("[Runtime/后台线程] asyncio 事件循环已创建")
        self._started.set()

        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self._loop = None

    def start(self) -> None:
        """启动后台线程，并等待事件循环准备完成。"""

        if self._thread is not None and self._thread.is_alive():
            return

        self._started.clear()
        thread = threading.Thread(
            target=self._run_event_loop,
            name="corecoder-mcp-runtime",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        # 避免后台启动异常时主线程永久等待。
        if not self._started.wait(timeout=5):
            raise RuntimeError("MCP Runtime 后台事件循环启动超时")
        logger.info("[Runtime/主线程] 后台事件循环已就绪")

    def close(self, graceful_timeout: float = 5.0, force_timeout: float = 3.0) -> None:
        """先尝试优雅关闭，超时后取消 Owner Task 并等待强制清理。"""

        if graceful_timeout <= 0 or force_timeout <= 0:
            raise ValueError("MCP Runtime 关闭超时时间必须大于 0")

        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            self._set_state(MCPRuntimeState.DISCONNECTED)
            return

        self._set_state(MCPRuntimeState.CLOSING)

        owner_future = self._owner_future
        commands = self._commands
        owner_error: BaseException | None = None
        if owner_future is not None and commands is not None:
            # 只发送关闭命令；真正的 client.close() 仍由 Owner Task 执行。
            logger.info("[Runtime/主线程] 向 Owner Task 发送关闭命令")
            loop.call_soon_threadsafe(commands.put_nowait, None)
            try:
                owner_future.result(timeout=graceful_timeout)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[Runtime/主线程] 优雅关闭超过 %s 秒，取消 Owner Task",
                    graceful_timeout,
                )
                owner_future.cancel()
                if not self._client_closed.wait(timeout=force_timeout):
                    owner_error = MCPRuntimeCloseError(
                        f"取消 Owner Task 后 {force_timeout} 秒内仍未完成 MCP Client 清理"
                    )
            except BaseException as error:
                owner_error = error
            finally:
                self._owner_future = None
                self._commands = None

        # 事件循环属于后台线程，因此必须用线程安全方法发送停止指令。
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=force_timeout)
        if thread.is_alive():
            self._set_state(MCPRuntimeState.FAILED)
            raise MCPRuntimeCloseError(f"MCP Runtime 后台线程在 {force_timeout} 秒内未退出")

        self._thread = None
        logger.info("[Runtime/主线程] 后台事件循环和线程已关闭")
        if owner_error is not None:
            self._set_state(MCPRuntimeState.FAILED)
            raise owner_error
        self._set_state(MCPRuntimeState.DISCONNECTED)

    def _submit(self, coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
        """把异步任务提交到后台事件循环，并同步等待执行结果。"""

        loop = self._loop
        if loop is None or not loop.is_running():
            coroutine.close()
            raise RuntimeError("MCP Runtime 尚未启动，请先调用 start()")

        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=5)

    def connect(self, command: str, args: list[str] | None = None) -> None:
        """启动长期 Owner Task，由它建立并持有 MCP 连接。"""

        if self._client is not None:
            self._raise_if_unhealthy()
            return

        # 旧连接已经完全清理后，显式重连会开启一个新的健康周期。
        self._unhealthy_reason = None
        self._connection_generation += 1
        self._set_state(MCPRuntimeState.CONNECTING)
        self.start()
        loop = self._loop
        if loop is None:
            raise RuntimeError("MCP Runtime 后台事件循环未准备完成")

        self._client_ready.clear()
        self._client_closed.clear()
        logger.info("[Runtime/主线程] 提交 Owner Task，准备建立 MCP 连接")
        owner_future = asyncio.run_coroutine_threadsafe(self._run_client_owner(command, args), loop)
        self._owner_future = owner_future

        if not self._client_ready.wait(timeout=5):
            self._set_state(MCPRuntimeState.FAILED)
            raise RuntimeError("MCP Client 后台连接超时")
        if owner_future.done():
            # Owner 提前结束表示连接失败，把后台的原始异常交回主线程。
            try:
                owner_future.result()
            except BaseException:
                self._set_state(MCPRuntimeState.FAILED)
                raise
        self._set_state(MCPRuntimeState.HEALTHY)
        logger.info("[Runtime/主线程] MCP Client 已连接")

    def call_tool(self, name: str, arguments: dict, timeout: float = 5.0) -> MCPToolCallResult:
        """同步发送工具调用命令，并等待 Owner Task 返回 MCP 结果。"""

        if timeout <= 0:
            raise ValueError("MCP 工具调用超时时间必须大于 0")

        loop = self._loop
        commands = self._commands
        if self._client is None or loop is None or commands is None:
            raise RuntimeError("MCP Runtime 尚未连接，请先调用 connect()")
        self._raise_if_unhealthy()

        reply: concurrent.futures.Future[MCPToolCallResult] = concurrent.futures.Future()
        command = _CallToolCommand(name=name, arguments=arguments, reply=reply)
        started = time.perf_counter()

        # Queue 属于后台 Loop，因此让 Loop 自己执行 put_nowait()。
        logger.info("[Runtime/主线程] 将工具调用命令放入队列：name=%s", name)
        loop.call_soon_threadsafe(commands.put_nowait, command)
        try:
            result = reply.result(timeout=timeout)
        except concurrent.futures.TimeoutError as error:
            self._unhealthy_reason = f"工具 {name!r} 调用超时（{timeout} 秒）"
            self._set_state(MCPRuntimeState.DEGRADED)
            self._record_call(name, started, MCPCallOutcome.TIMEOUT, str(self._unhealthy_reason))
            logger.warning("[Runtime/主线程] 工具调用超时：name=%s, timeout=%s", name, timeout)
            raise MCPToolTimeoutError(name, timeout) from error
        except MCPToolExecutionError as error:
            self._record_call(name, started, MCPCallOutcome.EXECUTION_ERROR, str(error))
            raise
        except Exception as error:
            self._unhealthy_reason = f"工具 {name!r} 发生传输故障：{error}"
            self._set_state(MCPRuntimeState.DEGRADED)
            self._record_call(name, started, MCPCallOutcome.TRANSPORT_ERROR, str(error))
            raise MCPTransportError(name, error) from error
        self._record_call(name, started, MCPCallOutcome.SUCCESS)
        logger.info("[Runtime/主线程] 收到 Owner Task 回复：%s", result.text)
        return result

    def list_tools(self) -> list[DiscoveredTool]:
        """同步请求 Owner Task 从当前 MCP 连接发现工具。"""

        loop = self._loop
        commands = self._commands
        if self._client is None or loop is None or commands is None:
            raise RuntimeError("MCP Runtime 尚未连接，请先调用 connect()")
        self._raise_if_unhealthy()

        reply: concurrent.futures.Future[list[DiscoveredTool]] = concurrent.futures.Future()
        command = _ListToolsCommand(reply=reply)
        loop.call_soon_threadsafe(commands.put_nowait, command)
        tools = reply.result(timeout=5)
        self._discovered_tools = {tool.name: tool for tool in tools}
        return tools

    def call_tool_with_retry(
        self,
        name: str,
        arguments: dict,
        *,
        max_attempts: int = 2,
        timeout: float = 5.0,
        backoff_seconds: float = 0.05,
    ) -> MCPToolCallResult:
        """仅对 Server 明确可重试、且工具明确安全的执行错误进行重试。"""

        if max_attempts <= 0:
            raise ValueError("MCP 工具最大尝试次数必须大于 0")
        if backoff_seconds < 0:
            raise ValueError("MCP 工具重试等待时间不能小于 0")

        tool = self._discovered_tools.get(name)
        for attempt in range(1, max_attempts + 1):
            try:
                return self.call_tool(name, arguments, timeout=timeout)
            except MCPToolExecutionError as error:
                should_retry = (
                    attempt < max_attempts
                    and error.retryable
                    and tool is not None
                    and tool.retry_safe
                )
                if not should_retry:
                    raise
                logger.warning(
                    "[Runtime/重试] tool=%s attempt=%s/%s，等待 %.3f 秒后重试",
                    name,
                    attempt,
                    max_attempts,
                    backoff_seconds,
                )
                if backoff_seconds:
                    time.sleep(backoff_seconds)

        raise AssertionError("工具重试循环不应执行到此处")

    def _raise_if_unhealthy(self) -> None:
        """拒绝把新命令发送到已经出现超时的连接。"""

        if self._unhealthy_reason is not None:
            raise MCPRuntimeUnhealthyError(self._unhealthy_reason)

    @property
    def state(self) -> MCPRuntimeState:
        """返回线程安全的当前生命周期状态。"""

        with self._state_lock:
            return self._state

    def _set_state(self, state: MCPRuntimeState) -> None:
        """原子更新状态，并记录可用于排障的状态转换日志。"""

        with self._state_lock:
            previous = self._state
            self._state = state
        if previous is not state:
            logger.info("[Runtime/状态] %s -> %s", previous.value, state.value)

    @property
    def call_history(self) -> tuple[MCPCallRecord, ...]:
        """返回最近 100 次调用的不可变快照。"""

        with self._history_lock:
            return tuple(self._call_history)

    def _record_call(
        self,
        tool_name: str,
        started: float,
        outcome: MCPCallOutcome,
        error: str | None = None,
    ) -> None:
        """记录一次调用；历史有上限，避免长期运行时无限占用内存。"""

        record = MCPCallRecord(
            tool_name=tool_name,
            connection_generation=self._connection_generation,
            duration_seconds=time.perf_counter() - started,
            outcome=outcome,
            error=error,
        )
        with self._history_lock:
            self._call_history.append(record)
        logger.info(
            "[Runtime/调用] tool=%s generation=%s outcome=%s duration=%.4fs",
            record.tool_name,
            record.connection_generation,
            record.outcome.value,
            record.duration_seconds,
        )

    async def _run_client_owner(self, command: str, args: list[str] | None) -> None:
        """在同一个 Task 中完成 MCP 连接、等待命令和关闭。"""

        client = PersistentMCPClient(command, args)
        commands: asyncio.Queue[_CallToolCommand | _ListToolsCommand | None] = asyncio.Queue()
        self._commands = commands

        try:
            await client.connect()
            self._client = client
            self._client_ready.set()

            while True:
                command_item = await commands.get()
                if command_item is None:
                    logger.info("[Owner Task/后台线程] 收到关闭命令")
                    break

                try:
                    if isinstance(command_item, _CallToolCommand):
                        logger.info("[Owner Task/后台线程] 取出工具调用命令：name=%s", command_item.name)
                        result = await client.call_tool(command_item.name, command_item.arguments)
                    else:
                        logger.info("[Owner Task/后台线程] 取出工具发现命令")
                        result = await client.list_tools()
                except asyncio.CancelledError:
                    # 强制关闭时必须让取消继续传播到外层 finally，不能把它
                    # 误当成一次普通工具错误，否则 Client 和 Server 无法清理。
                    raise
                except BaseException as error:
                    command_item.reply.set_exception(error)
                else:
                    command_item.reply.set_result(result)
        except BaseException:
            self._client_ready.set()
            raise
        finally:
            try:
                logger.info("[Owner Task/后台线程] 关闭 MCP Client")
                await client.close()
            finally:
                self._client = None
                self._client_closed.set()
