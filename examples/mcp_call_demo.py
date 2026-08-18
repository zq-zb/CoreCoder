"""手动体验 MCP 工具发现和调用的最小示例。"""

import asyncio
import sys
from pathlib import Path

from corecoder.mcp_client import call_stdio_tool, discover_stdio_tools


async def main() -> None:
    """启动演示 Server，依次展示工具发现和两次真实调用。"""

    server_path = Path(__file__).with_name("mcp_demo_server.py")
    server_args = [str(server_path)]

    tools = await discover_stdio_tools(sys.executable, server_args)
    print("发现工具：")
    for tool in tools:
        print(f"- {tool.name}")

    add_result = await call_stdio_tool(
        sys.executable,
        "add",
        {"a": 2, "b": 3},
        server_args,
    )
    print(f"\n调用 add：\n{add_result.text}")

    greet_result = await call_stdio_tool(
        sys.executable,
        "greet",
        {"name": "小明"},
        server_args,
    )
    print(f"\n调用 greet：\n{greet_result.text}")


if __name__ == "__main__":
    asyncio.run(main())
