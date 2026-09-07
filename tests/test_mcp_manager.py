"""多 MCP Server 管理与故障隔离测试。"""

import concurrent.futures
import sys
import time
from pathlib import Path

import pytest

from corecoder.mcp_client import MCPToolExecutionError
from corecoder.mcp_manager import (
    MCPCircuitOpenError,
    MCPCircuitState,
    MCPManager,
    MCPServerBusyError,
    MCPServerConfig,
)
from corecoder.mcp_runtime import MCPRuntimeState, MCPToolTimeoutError

ROOT = Path(__file__).parents[1]
NORMAL_SERVER = ROOT / "examples" / "mcp_demo_server.py"
SLOW_SERVER = ROOT / "tests" / "fixtures" / "mcp_slow_server.py"
RETRY_SERVER = ROOT / "tests" / "fixtures" / "mcp_retry_server.py"


def test_manager_namespaces_tools_from_multiple_servers():
    """不同 Server 的工具必须拥有不会冲突的公开名称。"""

    manager = MCPManager()
    manager.add_server(MCPServerConfig("primary", sys.executable, (str(NORMAL_SERVER),)))
    manager.add_server(MCPServerConfig("backup", sys.executable, (str(NORMAL_SERVER),)))
    try:
        tools = manager.create_tools()
    finally:
        manager.close()

    assert {tool.name for tool in tools} == {
        "primary__add",
        "primary__greet",
        "backup__add",
        "backup__greet",
    }


def test_manager_rejects_non_positive_server_call_timeout():
    """每 Server 的默认调用期限必须是有效正数。"""

    manager = MCPManager()
    with pytest.raises(ValueError, match="超时时间必须大于 0"):
        manager.add_server(MCPServerConfig("broken", sys.executable, (), call_timeout=0))


def test_manager_routes_agent_call_through_conservative_retry():
    """Manager 路径也应复用 Runtime 的 MCP 安全注解重试规则。"""

    manager = MCPManager(max_retry_attempts=2, retry_backoff_seconds=0)
    manager.add_server(MCPServerConfig("retry", sys.executable, (str(RETRY_SERVER),)))
    try:
        tools = {tool.name: tool for tool in manager.create_tools()}
        result = tools["retry__flaky_read"].execute()
        history = manager._runtimes["retry"].call_history
    finally:
        manager.close()

    assert result == "读取成功"
    assert [record.outcome.value for record in history] == ["execution_error", "success"]


def test_one_server_timeout_does_not_block_another_server():
    """慢 Server 降级后，正常 Server 的独立 Runtime 仍应可用。"""

    manager = MCPManager()
    manager.add_server(MCPServerConfig("math", sys.executable, (str(NORMAL_SERVER),)))
    manager.add_server(MCPServerConfig("slow", sys.executable, (str(SLOW_SERVER),)))
    try:
        with pytest.raises(MCPToolTimeoutError):
            manager.call_tool(
                "slow",
                "slow_echo",
                {"text": "hello", "delay": 0.2},
                timeout=0.05,
            )

        assert manager.state("slow") is MCPRuntimeState.DEGRADED
        assert manager.state("math") is MCPRuntimeState.HEALTHY
        result = manager.call_tool("math", "add", {"a": 20, "b": 22})
    finally:
        manager.close()

    assert result.text == "42"


def test_manager_opens_circuit_after_repeated_transient_failures():
    """连续瞬时错误达到阈值后，应快速失败而不再请求 Server。"""

    manager = MCPManager(failure_threshold=2, recovery_timeout=30)
    manager.add_server(MCPServerConfig("unstable", sys.executable, (str(RETRY_SERVER),)))
    try:
        for _ in range(2):
            with pytest.raises(MCPToolExecutionError):
                manager.call_tool("unstable", "always_transient_error", {})

        assert manager.circuit_state("unstable") is MCPCircuitState.OPEN
        with pytest.raises(MCPCircuitOpenError, match="已熔断"):
            manager.call_tool("unstable", "always_transient_error", {})
    finally:
        manager.close()


def test_manager_closes_circuit_after_successful_half_open_probe():
    """恢复窗口结束后的单次成功探测，应让 Server 回到 CLOSED。"""

    manager = MCPManager(failure_threshold=1, recovery_timeout=0.01)
    manager.add_server(MCPServerConfig("recovering", sys.executable, (str(RETRY_SERVER),)))
    try:
        with pytest.raises(MCPToolExecutionError):
            manager.call_tool("recovering", "flaky_read", {})
        assert manager.circuit_state("recovering") is MCPCircuitState.OPEN

        time.sleep(0.02)
        result = manager.call_tool("recovering", "flaky_read", {})
    finally:
        manager.close()

    assert result.text == "读取成功"


def test_manager_bulkhead_rejects_excess_concurrency_before_queueing():
    """单 Server 并发槽耗尽时，新请求应快速失败而不是无限排队。"""

    manager = MCPManager(max_concurrency_per_server=1, acquire_timeout=0.01)
    manager.add_server(MCPServerConfig("slow", sys.executable, (str(SLOW_SERVER),)))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                manager.call_tool,
                "slow",
                "slow_echo",
                {"text": "first", "delay": 0.2},
            )
            time.sleep(0.05)
            second = pool.submit(manager.call_tool, "slow", "slow_echo", {"text": "second"})

            with pytest.raises(MCPServerBusyError, match="并发调用已达到 1"):
                second.result()
            assert first.result().text == "first"
    finally:
        manager.close()


def test_manager_cleans_runtime_when_server_connection_fails(monkeypatch):
    """注册期间连接失败时，不应遗留刚创建的 Runtime 资源。"""

    class FailingRuntime:
        def __init__(self):
            self.closed = False

        def connect(self, command, args):
            raise OSError("无法启动测试 Server")

        def close(self):
            self.closed = True

    runtime = FailingRuntime()
    monkeypatch.setattr("corecoder.mcp_manager.MCPRuntime", lambda: runtime)
    manager = MCPManager()

    with pytest.raises(OSError, match="无法启动"):
        manager.add_server(MCPServerConfig("broken", "missing-command"))

    assert runtime.closed is True


def test_manager_restarts_only_degraded_server():
    """单 Server 重启应恢复其服务，同时不替换其他健康 Runtime。"""

    manager = MCPManager()
    manager.add_server(MCPServerConfig("math", sys.executable, (str(NORMAL_SERVER),)))
    manager.add_server(MCPServerConfig("slow", sys.executable, (str(SLOW_SERVER),)))
    healthy_runtime = manager._runtimes["math"]
    try:
        with pytest.raises(MCPToolTimeoutError):
            manager.call_tool("slow", "slow_echo", {"text": "late", "delay": 10.0}, timeout=0.05)

        manager.restart_server("slow", graceful_timeout=0.05, force_timeout=5.0)

        assert manager.state("slow") is MCPRuntimeState.HEALTHY
        assert manager._runtimes["math"] is healthy_runtime
        slow_result = manager.call_tool("slow", "slow_echo", {"text": "recovered", "delay": 0})
        math_result = manager.call_tool("math", "add", {"a": 20, "b": 22})
    finally:
        manager.close()

    assert slow_result.text == "recovered"
    assert math_result.text == "42"
