"""MCP 后台 Runtime 测试。"""

import asyncio
import concurrent.futures
import sys
import threading
import time
from pathlib import Path

import pytest

from corecoder.mcp_client import DiscoveredTool, MCPToolExecutionError
from corecoder.mcp_runtime import (
    MCPCallOutcome,
    MCPRuntime,
    MCPRuntimeCloseError,
    MCPRuntimeState,
    MCPRuntimeUnhealthyError,
    MCPToolTimeoutError,
    MCPTransportError,
)
from corecoder.tools.mcp import MCPToolAdapter, create_mcp_tool_adapters

SERVER_PATH = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"
SLOW_SERVER_PATH = Path(__file__).parent / "fixtures" / "mcp_slow_server.py"
ERROR_SERVER_PATH = Path(__file__).parent / "fixtures" / "mcp_error_server.py"
RETRY_SERVER_PATH = Path(__file__).parent / "fixtures" / "mcp_retry_server.py"
CRASH_SERVER_PATH = Path(__file__).parent / "fixtures" / "mcp_crash_server.py"


def test_runtime_starts_and_stops_background_event_loop():
    """Runtime 应启动可用的后台事件循环，并能安全停止。"""

    runtime = MCPRuntime()
    runtime.start()

    assert runtime._thread is not None
    assert runtime._thread.is_alive()
    assert runtime._loop is not None
    assert runtime._loop.is_running()

    runtime.close()

    assert runtime._thread is None
    assert runtime._loop is None


def test_runtime_submits_coroutine_to_background_thread():
    """同步主线程应能提交异步任务，并取得后台执行结果。"""

    async def identify_thread() -> str:
        return threading.current_thread().name

    runtime = MCPRuntime()
    runtime.start()
    try:
        worker_name = runtime._submit(identify_thread())
    finally:
        runtime.close()

    assert worker_name == "corecoder-mcp-runtime"


def test_runtime_connects_and_closes_real_mcp_server():
    """Runtime 应在后台 Loop 中建立并释放真实 stdio MCP 连接。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SERVER_PATH)])

    assert runtime.state is MCPRuntimeState.HEALTHY
    assert runtime._client is not None
    assert runtime._client._client is not None

    runtime.close()

    assert runtime.state is MCPRuntimeState.DISCONNECTED
    assert runtime._client is None
    assert runtime._client_closed.is_set()
    assert runtime._thread is None
    assert runtime._loop is None


def test_runtime_discovers_tools_through_owner_task():
    """Runtime 应通过 Owner Task 在当前连接中发现真实 MCP 工具。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SERVER_PATH)])
    try:
        tools = runtime.list_tools()
    finally:
        runtime.close()

    assert {tool.name for tool in tools} == {"add", "greet"}


def test_adapter_calls_real_mcp_tool_through_runtime():
    """Adapter 应通过 Runtime 和 Owner Task 调用真实 MCP 工具。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SERVER_PATH)])
    adapter = MCPToolAdapter(
        DiscoveredTool(
            name="add",
            description="把两个整数相加。",
            input_schema={"type": "object"},
        ),
        runtime,
    )

    try:
        result = adapter.execute(a=2, b=3)
    finally:
        runtime.close()

    assert result == "5"


def test_dynamically_discovers_and_adapts_real_mcp_tools():
    """真实 Server 工具应自动转换成可直接执行的 CoreCoder Tool。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SERVER_PATH)])
    try:
        tools = create_mcp_tool_adapters(runtime)
        tools_by_name = {tool.name: tool for tool in tools}
        result = tools_by_name["add"].execute(a=2, b=3)
    finally:
        runtime.close()

    assert set(tools_by_name) == {"add", "greet"}
    assert result == "5"


def test_runtime_reports_tool_name_when_call_times_out():
    """慢工具超时后，应返回包含工具上下文的专用异常。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SLOW_SERVER_PATH)])
    try:
        with pytest.raises(MCPToolTimeoutError, match="slow_echo.*0.05"):
            runtime.call_tool(
                "slow_echo",
                {"text": "hello", "delay": 0.2},
                timeout=0.05,
            )
        assert runtime.state is MCPRuntimeState.DEGRADED
    finally:
        runtime.close()


def test_runtime_rejects_new_commands_after_timeout_and_recovers_after_reconnect():
    """超时连接应被隔离，完成清理并重连后才恢复服务。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SLOW_SERVER_PATH)])
    try:
        with pytest.raises(MCPToolTimeoutError):
            runtime.call_tool(
                "slow_echo",
                {"text": "hello", "delay": 0.2},
                timeout=0.05,
            )

        with pytest.raises(MCPRuntimeUnhealthyError, match="slow_echo"):
            runtime.list_tools()
        with pytest.raises(MCPRuntimeUnhealthyError, match="slow_echo"):
            runtime.call_tool("slow_echo", {"text": "again"})
    finally:
        # close() 会等待已经发出的慢调用收尾，再清理旧连接。
        runtime.close()

    runtime.connect(sys.executable, [str(SERVER_PATH)])
    try:
        result = runtime.call_tool("add", {"a": 20, "b": 22})
    finally:
        runtime.close()

    assert result.text == "42"


def test_runtime_force_closes_tool_that_does_not_finish_in_grace_period():
    """长时间工具不应让 Runtime 等到工具自然执行结束。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SLOW_SERVER_PATH)])
    with pytest.raises(MCPToolTimeoutError):
        runtime.call_tool(
            "slow_echo",
            {"text": "never-wait-this-long", "delay": 10.0},
            timeout=0.05,
        )

    started = time.perf_counter()
    runtime.close(graceful_timeout=0.05, force_timeout=5.0)
    elapsed = time.perf_counter() - started

    assert elapsed < 8.0
    assert runtime._client_closed.is_set()
    assert runtime._client is None
    assert runtime._thread is None

    # 强制清理旧 Server 后，同一个 Runtime 仍可建立全新连接。
    runtime.connect(sys.executable, [str(SERVER_PATH)])
    try:
        result = runtime.call_tool("add", {"a": 20, "b": 22})
    finally:
        runtime.close()

    assert result.text == "42"


def test_runtime_reports_failed_state_when_forced_cleanup_cannot_finish():
    """强制清理也超时时，Runtime 应有限返回并暴露 FAILED 状态。"""

    class FakeLoop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

        def stop(self):
            return None

    class FakeThread:
        def join(self, timeout):
            return None

        def is_alive(self):
            return False

    runtime = MCPRuntime()
    runtime._loop = FakeLoop()
    runtime._thread = FakeThread()
    runtime._commands = asyncio.Queue()
    runtime._owner_future = concurrent.futures.Future()

    with pytest.raises(MCPRuntimeCloseError, match="仍未完成 MCP Client 清理"):
        runtime.close(graceful_timeout=0.01, force_timeout=0.01)

    assert runtime.state is MCPRuntimeState.FAILED


def test_tool_execution_error_does_not_poison_healthy_connection():
    """业务工具失败应被准确报告，但同一连接上的其他工具仍可调用。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(ERROR_SERVER_PATH)])
    try:
        # MCP SDK 可以隐藏 Server 的内部异常细节，因此只依赖稳定的工具名错误契约。
        with pytest.raises(MCPToolExecutionError, match="fail_operation") as captured:
            runtime.call_tool("fail_operation", {"reason": "库存不足"})

        assert captured.value.tool_name == "fail_operation"
        assert runtime.state is MCPRuntimeState.HEALTHY

        result = runtime.call_tool("echo", {"text": "连接仍然可用"})
        history = runtime.call_history
    finally:
        runtime.close()

    assert result.text == "连接仍然可用"
    assert [record.outcome for record in history] == [
        MCPCallOutcome.EXECUTION_ERROR,
        MCPCallOutcome.SUCCESS,
    ]
    assert all(record.duration_seconds >= 0 for record in history)
    assert history[0].connection_generation == history[1].connection_generation


def test_runtime_retries_only_explicitly_safe_transient_tool_error():
    """可重试错误和只读/幂等注解同时存在时，才允许自动重试。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(RETRY_SERVER_PATH)])
    try:
        tools = runtime.list_tools()
        result = runtime.call_tool_with_retry("flaky_read", {}, max_attempts=2, backoff_seconds=0)
        history = runtime.call_history
    finally:
        runtime.close()

    assert tools[0].retry_safe is True
    assert result.text == "读取成功"
    assert [record.outcome for record in history] == [
        MCPCallOutcome.EXECUTION_ERROR,
        MCPCallOutcome.SUCCESS,
    ]


def test_runtime_does_not_retry_tool_without_safety_and_retryable_metadata():
    """没有安全注解或 retryable 标记时，即使配置多次尝试也只能调用一次。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(ERROR_SERVER_PATH)])
    try:
        runtime.list_tools()
        with pytest.raises(MCPToolExecutionError):
            runtime.call_tool_with_retry("fail_operation", {"reason": "永久错误"}, max_attempts=3)
        history = runtime.call_history
    finally:
        runtime.close()

    assert len(history) == 1
    assert history[0].outcome is MCPCallOutcome.EXECUTION_ERROR


def test_runtime_call_history_keeps_only_latest_one_hundred_records():
    """调用历史超过容量时，应自动淘汰最旧记录而不是无限增长。"""

    runtime = MCPRuntime()
    for index in range(101):
        runtime._record_call(
            f"tool_{index}",
            time.perf_counter(),
            MCPCallOutcome.SUCCESS,
        )

    history = runtime.call_history
    assert len(history) == 100
    assert history[0].tool_name == "tool_1"
    assert history[-1].tool_name == "tool_100"


def test_server_process_crash_is_classified_as_transport_failure():
    """Server 未返回响应就退出时，应降级连接并记录 transport_error。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(CRASH_SERVER_PATH)])
    try:
        with pytest.raises(MCPTransportError, match="crash.*传输故障"):
            runtime.call_tool("crash", {}, timeout=2)

        assert runtime.state is MCPRuntimeState.DEGRADED
        assert runtime.call_history[-1].outcome is MCPCallOutcome.TRANSPORT_ERROR
    finally:
        runtime.close()
