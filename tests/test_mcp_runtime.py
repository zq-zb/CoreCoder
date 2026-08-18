"""MCP 后台 Runtime 测试。"""

import sys
import threading
from pathlib import Path

from corecoder.mcp_client import DiscoveredTool
from corecoder.mcp_runtime import MCPRuntime
from corecoder.tools.mcp import MCPToolAdapter, create_mcp_tool_adapters

SERVER_PATH = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"


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

    assert runtime._client is not None
    assert runtime._client._client is not None

    runtime.close()

    assert runtime._client is None
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
