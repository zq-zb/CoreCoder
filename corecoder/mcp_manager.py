"""管理多个相互隔离的 MCP Server Runtime。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from corecoder.mcp_client import MCPToolCallResult, MCPToolExecutionError
from corecoder.mcp_runtime import MCPRuntime, MCPRuntimeState, MCPToolTimeoutError, MCPTransportError
from corecoder.tools.mcp import MCPToolAdapter


@dataclass(frozen=True)
class MCPServerConfig:
    """一个 stdio MCP Server 的启动配置。"""

    name: str
    command: str
    args: tuple[str, ...] = ()
    call_timeout: float = 5.0


class MCPServerNotFoundError(KeyError):
    """请求了尚未注册的 MCP Server。"""


class MCPCircuitState(str, Enum):
    """单个 MCP Server 的熔断状态。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class MCPCircuitOpenError(RuntimeError):
    """目标 Server 的熔断器处于开启状态。"""


class MCPServerBusyError(RuntimeError):
    """目标 Server 的并发舱壁已满，调用未进入 Runtime 队列。"""


@dataclass
class _Circuit:
    state: MCPCircuitState = MCPCircuitState.CLOSED
    failures: int = 0
    opened_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class _ManagedServerCaller:
    """把 Adapter 的调用绑定到 Manager 中的指定 Server。"""

    def __init__(self, manager: MCPManager, server_name: str) -> None:
        self._manager = manager
        self._server_name = server_name

    def call_tool(self, name: str, arguments: dict) -> MCPToolCallResult:
        timeout = self._manager._configs[self._server_name].call_timeout
        return self._manager.call_tool(self._server_name, name, arguments, timeout=timeout)


class MCPManager:
    """让每个 MCP Server 使用独立 Runtime，实现故障域隔离。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        max_concurrency_per_server: int = 8,
        acquire_timeout: float = 0.1,
        max_retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.05,
    ) -> None:
        if failure_threshold <= 0 or recovery_timeout <= 0 or max_concurrency_per_server <= 0:
            raise ValueError("熔断阈值、恢复时间和 Server 并发数必须大于 0")
        if acquire_timeout < 0:
            raise ValueError("并发槽等待时间不能小于 0")
        if max_retry_attempts <= 0 or retry_backoff_seconds < 0:
            raise ValueError("重试次数必须大于 0，重试等待时间不能小于 0")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.max_concurrency_per_server = max_concurrency_per_server
        self.acquire_timeout = acquire_timeout
        self.max_retry_attempts = max_retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self._configs: dict[str, MCPServerConfig] = {}
        self._runtimes: dict[str, MCPRuntime] = {}
        self._circuits: dict[str, _Circuit] = {}
        self._slots: dict[str, threading.BoundedSemaphore] = {}

    def add_server(self, config: MCPServerConfig) -> None:
        """注册并连接一个 Server；名称重复时拒绝覆盖。"""

        if config.name in self._configs:
            raise ValueError(f"MCP Server 名称重复：{config.name}")
        if config.call_timeout <= 0:
            raise ValueError("MCP Server 工具调用超时时间必须大于 0")
        runtime = MCPRuntime()
        try:
            runtime.connect(config.command, list(config.args))
        except BaseException:
            runtime.close()
            raise
        self._configs[config.name] = config
        self._runtimes[config.name] = runtime
        self._circuits[config.name] = _Circuit()
        self._slots[config.name] = threading.BoundedSemaphore(self.max_concurrency_per_server)

    def create_tools(self) -> list[MCPToolAdapter]:
        """发现所有 Server 工具，并用 server__tool 生成稳定且无冲突的名称。"""

        adapters: list[MCPToolAdapter] = []
        for server_name, runtime in self._runtimes.items():
            caller = _ManagedServerCaller(self, server_name)
            for discovered_tool in runtime.list_tools():
                adapters.append(
                    MCPToolAdapter(
                        discovered_tool,
                        caller,
                        public_name=f"{server_name}__{discovered_tool.name}",
                    )
                )
        return adapters

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        *,
        timeout: float = 5.0,
    ) -> MCPToolCallResult:
        """只把调用路由到目标 Server 的独立 Runtime。"""

        runtime = self._runtime(server_name)
        circuit = self._circuits[server_name]
        slot = self._slots[server_name]
        self._check_circuit(server_name, circuit)
        if not slot.acquire(timeout=self.acquire_timeout):
            raise MCPServerBusyError(
                f"MCP Server {server_name!r} 并发调用已达到 {self.max_concurrency_per_server}"
            )
        try:
            try:
                # 复用 Runtime 的保守重试规则：只有工具明确安全，
                # 且 Server 明确声明本次错误可重试时，才会执行第二次调用。
                result = runtime.call_tool_with_retry(
                    tool_name,
                    arguments,
                    max_attempts=self.max_retry_attempts,
                    timeout=timeout,
                    backoff_seconds=self.retry_backoff_seconds,
                )
            except MCPToolExecutionError as error:
                if error.retryable:
                    self._record_failure(circuit)
                raise
            except MCPToolTimeoutError:
                self._record_failure(circuit)
                raise
            except MCPTransportError:
                self._record_failure(circuit)
                raise
            else:
                with circuit.lock:
                    circuit.state = MCPCircuitState.CLOSED
                    circuit.failures = 0
                    circuit.opened_at = None
                return result
        finally:
            slot.release()

    def state(self, server_name: str) -> MCPRuntimeState:
        """查看单个 Server 的隔离状态。"""

        return self._runtime(server_name).state

    def restart_server(
        self,
        server_name: str,
        *,
        graceful_timeout: float = 1.0,
        force_timeout: float = 3.0,
    ) -> None:
        """只重建指定 Server 的 Runtime，不中断其他 Server。"""

        old_runtime = self._runtime(server_name)
        config = self._configs[server_name]
        old_runtime.close(graceful_timeout=graceful_timeout, force_timeout=force_timeout)

        new_runtime = MCPRuntime()
        try:
            new_runtime.connect(config.command, list(config.args))
        except BaseException:
            new_runtime.close()
            self._runtimes.pop(server_name, None)
            raise

        self._runtimes[server_name] = new_runtime
        self._circuits[server_name] = _Circuit()
        self._slots[server_name] = threading.BoundedSemaphore(self.max_concurrency_per_server)

    def circuit_state(self, server_name: str) -> MCPCircuitState:
        """查看指定 Server 的熔断状态。"""

        self._runtime(server_name)
        circuit = self._circuits[server_name]
        with circuit.lock:
            return circuit.state

    def close(self) -> None:
        """尽力关闭所有 Server；一个关闭失败不阻止其余 Server 清理。"""

        errors: list[str] = []
        for server_name, runtime in self._runtimes.items():
            try:
                runtime.close()
            except BaseException as error:
                errors.append(f"{server_name}: {error}")
        self._runtimes.clear()
        self._configs.clear()
        self._circuits.clear()
        self._slots.clear()
        if errors:
            raise RuntimeError("部分 MCP Server 关闭失败：" + "; ".join(errors))

    def _runtime(self, server_name: str) -> MCPRuntime:
        try:
            return self._runtimes[server_name]
        except KeyError:
            raise MCPServerNotFoundError(f"未注册 MCP Server：{server_name}") from None

    def _check_circuit(self, server_name: str, circuit: _Circuit) -> None:
        """OPEN 窗口内快速失败，窗口结束后放行一次 HALF_OPEN 探测。"""

        with circuit.lock:
            if circuit.state is MCPCircuitState.CLOSED:
                return
            if circuit.state is MCPCircuitState.HALF_OPEN:
                raise MCPCircuitOpenError(f"MCP Server {server_name!r} 正在执行恢复探测")
            assert circuit.opened_at is not None
            elapsed = time.monotonic() - circuit.opened_at
            if elapsed < self.recovery_timeout:
                remaining = self.recovery_timeout - elapsed
                raise MCPCircuitOpenError(f"MCP Server {server_name!r} 已熔断，约 {remaining:.2f} 秒后允许探测")
            circuit.state = MCPCircuitState.HALF_OPEN

    def _record_failure(self, circuit: _Circuit) -> None:
        """累计瞬时/连接故障，达到阈值后开启熔断。"""

        with circuit.lock:
            circuit.failures += 1
            if circuit.state is MCPCircuitState.HALF_OPEN or circuit.failures >= self.failure_threshold:
                circuit.state = MCPCircuitState.OPEN
                circuit.opened_at = time.monotonic()
