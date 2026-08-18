"""运行 Adapter → Runtime → MCP Client → Server 的完整真实调用。"""

import sys
from pathlib import Path

from corecoder.mcp_client import DiscoveredTool
from corecoder.mcp_runtime import MCPRuntime
from corecoder.tools.mcp import MCPToolAdapter


def main() -> None:
    """通过 CoreCoder Tool 接口调用 MCP Server 的 add 工具。"""

    server_path = Path(__file__).with_name("mcp_demo_server.py")
    runtime = MCPRuntime()

    print("1. Connect MCP Runtime")
    runtime.connect(sys.executable, [str(server_path)])

    adapter = MCPToolAdapter(
        DiscoveredTool(
            name="add",
            description="Add two integers.",
            input_schema={"type": "object"},
        ),
        runtime,
    )

    try:
        print("2. Agent calls adapter.execute(a=2, b=3)")
        result = adapter.execute(a=2, b=3)
        print(f"3. MCP result: {result}")
    finally:
        runtime.close()
        print("4. Runtime closed")


if __name__ == "__main__":
    main()
