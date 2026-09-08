"""MCP 工具到 CoreCoder Tool 的适配测试。"""

from corecoder.mcp_client import DiscoveredTool, MCPToolCallResult
from corecoder.tools.mcp import MCPToolAdapter


class FakeRuntime:
    """只记录调用参数，不启动真实 MCP Server。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict) -> MCPToolCallResult:
        self.calls.append((name, arguments))
        return MCPToolCallResult(text="5", is_error=False)


def test_adapts_mcp_tool_schema_for_agent():
    """MCP 工具定义应转换成 Agent 发送给 LLM 的函数 Schema。"""

    discovered_tool = DiscoveredTool(
        name="add",
        description="把两个整数相加。",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    )

    adapter = MCPToolAdapter(discovered_tool, FakeRuntime())

    assert adapter.schema() == {
        "type": "function",
        "function": {
            "name": "add",
            "description": "把两个整数相加。",
            "parameters": discovered_tool.input_schema,
        },
    }


def test_forwards_agent_call_to_mcp_runtime():
    """Adapter 应把工具名称和 Agent 参数原样转发给 Runtime。"""

    runtime = FakeRuntime()
    adapter = MCPToolAdapter(
        DiscoveredTool(
            name="add",
            description="把两个整数相加。",
            input_schema={"type": "object"},
        ),
        runtime,
    )

    result = adapter.execute(a=2, b=3)

    assert runtime.calls == [("add", {"a": 2, "b": 3})]
    assert result == "5"
