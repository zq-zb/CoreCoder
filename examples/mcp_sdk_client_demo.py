"""直接使用 MCP SDK，在同一个会话中连续调用多个工具。"""

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    """不经过 PersistentMCPClient，直接管理 SDK Client。"""

    server_path = Path(__file__).with_name("mcp_demo_server.py")
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
    )

    print("1. 准备建立原生 MCP SDK 连接")
    async with Client(stdio_client(server)) as client:
        print("2. 原生 MCP SDK 连接已建立")

        add_response = await client.call_tool(
            name="add",
            arguments={"a": 2, "b": 3},
        )
        print(f"3. add 原生返回对象：{type(add_response).__name__}")
        print(f"4. add 文本结果：{add_response.content[0].text}")

        greet_response = await client.call_tool(
            name="greet",
            arguments={"name": "小明"},
        )
        print(f"5. greet 文本结果：{greet_response.content[0].text}")
        print("6. 两次调用都发生在同一个 SDK Client 会话中")

    print("7. 离开 async with，原生 SDK 连接已关闭")


if __name__ == "__main__":
    asyncio.run(main())
