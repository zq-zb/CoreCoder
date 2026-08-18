"""把 MCP 工具定义适配成 CoreCoder 能识别的 Tool。"""

from typing import Protocol

from corecoder.mcp_client import DiscoveredTool, MCPToolCallResult
from corecoder.tools.base import Tool


class MCPToolCaller(Protocol):
    """Adapter 需要的最小调用接口，真实 Runtime 将在下一阶段实现。"""

    def call_tool(self, name: str, arguments: dict) -> MCPToolCallResult:
        """同步调用一个 MCP 工具。"""


class MCPToolDiscovery(MCPToolCaller, Protocol):
    """既能发现工具、又能调用工具的 Runtime 接口。"""

    def list_tools(self) -> list[DiscoveredTool]:
        """同步发现当前 MCP Server 提供的工具。"""


class MCPToolAdapter(Tool):
    """将 MCP 的名称、描述和输入 Schema 转换成 CoreCoder Tool。"""

    def __init__(self, discovered_tool: DiscoveredTool, runtime: MCPToolCaller) -> None:
        self.name = discovered_tool.name
        self.description = discovered_tool.description
        self.parameters = discovered_tool.input_schema
        self._runtime = runtime

    def execute(self, **kwargs) -> str:
        """把 Agent 的同步工具调用转交给 MCP Runtime。"""

        result = self._runtime.call_tool(self.name, kwargs)
        return result.text


def create_mcp_tool_adapters(runtime: MCPToolDiscovery) -> list[MCPToolAdapter]:
    """动态发现 MCP 工具，并转换成 Agent 可使用的 Tool 列表。"""

    return [MCPToolAdapter(tool, runtime) for tool in runtime.list_tools()]
