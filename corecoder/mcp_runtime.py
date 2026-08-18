"""在后台事件循环中运行持久化 MCP Client。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from corecoder.mcp_client import DiscoveredTool, MCPToolCallResult, PersistentMCPClient

ResultT = TypeVar("ResultT")


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

        # 主线程通过这个信号判断后台事件循环是否已经准备完成。
        self._started = threading.Event()
        self._client_ready = threading.Event()

    def _run_event_loop(self) -> None:
        """后台线程入口：创建事件循环，并持续等待异步任务。"""

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
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

    def close(self) -> None:
        """先关闭 MCP 连接，再停止后台事件循环和线程。"""

        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return

        owner_future = self._owner_future
        commands = self._commands
        owner_error: BaseException | None = None
        if owner_future is not None and commands is not None:
            # 只发送关闭命令；真正的 client.close() 仍由 Owner Task 执行。
            loop.call_soon_threadsafe(commands.put_nowait, None)
            try:
                owner_future.result(timeout=5)
            except BaseException as error:
                owner_error = error
            finally:
                self._owner_future = None
                self._commands = None

        # 事件循环属于后台线程，因此必须用线程安全方法发送停止指令。
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("MCP Runtime 后台线程关闭超时")

        self._thread = None
        if owner_error is not None:
            raise owner_error

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
            return

        self.start()
        loop = self._loop
        if loop is None:
            raise RuntimeError("MCP Runtime 后台事件循环未准备完成")

        self._client_ready.clear()
        owner_future = asyncio.run_coroutine_threadsafe(self._run_client_owner(command, args), loop)
        self._owner_future = owner_future

        if not self._client_ready.wait(timeout=5):
            raise RuntimeError("MCP Client 后台连接超时")
        if owner_future.done():
            # Owner 提前结束表示连接失败，把后台的原始异常交回主线程。
            owner_future.result()

    def call_tool(self, name: str, arguments: dict) -> MCPToolCallResult:
        """同步发送工具调用命令，并等待 Owner Task 返回 MCP 结果。"""

        loop = self._loop
        commands = self._commands
        if self._client is None or loop is None or commands is None:
            raise RuntimeError("MCP Runtime 尚未连接，请先调用 connect()")

        reply: concurrent.futures.Future[MCPToolCallResult] = concurrent.futures.Future()
        command = _CallToolCommand(name=name, arguments=arguments, reply=reply)

        # Queue 属于后台 Loop，因此让 Loop 自己执行 put_nowait()。
        loop.call_soon_threadsafe(commands.put_nowait, command)
        return reply.result(timeout=5)

    def list_tools(self) -> list[DiscoveredTool]:
        """同步请求 Owner Task 从当前 MCP 连接发现工具。"""

        loop = self._loop
        commands = self._commands
        if self._client is None or loop is None or commands is None:
            raise RuntimeError("MCP Runtime 尚未连接，请先调用 connect()")

        reply: concurrent.futures.Future[list[DiscoveredTool]] = concurrent.futures.Future()
        command = _ListToolsCommand(reply=reply)
        loop.call_soon_threadsafe(commands.put_nowait, command)
        return reply.result(timeout=5)

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
                    break

                try:
                    if isinstance(command_item, _CallToolCommand):
                        result = await client.call_tool(command_item.name, command_item.arguments)
                    else:
                        result = await client.list_tools()
                except BaseException as error:
                    command_item.reply.set_exception(error)
                else:
                    command_item.reply.set_result(result)
        except BaseException:
            self._client_ready.set()
            raise
        finally:
            try:
                await client.close()
            finally:
                self._client = None
