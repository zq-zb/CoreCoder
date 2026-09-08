"""演示 PersistentMCPClient 的连接生命周期。"""

import asyncio
import sys
from pathlib import Path

from corecoder.mcp_client import PersistentMCPClient


async def main() -> None:
    """建立一次 MCP 长连接，并在代码块结束时统一关闭。"""

    server_path = Path(__file__).with_name("mcp_demo_server.py")

    print("1. 准备建立 MCP 长连接")
    async with PersistentMCPClient(sys.executable, [str(server_path)]) as client:
        print("2. MCP 长连接已建立")
        connected_client = client._client

        add_result = await client.call_tool("add", {"a": 2, "b": 3})
        print(f"3. 第一次调用 add，结果：{add_result.text}")

        greet_result = await client.call_tool("greet", {"name": "小明"})
        print(f"4. 第二次调用 greet，结果：{greet_result.text}")

        reused = client._client is connected_client
        print(f"5. 两次调用是否复用同一个底层 Client：{reused}")
        print("6. 两次调用结束，但仍在 async with 内，连接尚未关闭")

    print("7. 离开 async with，MCP 长连接已关闭")


if __name__ == "__main__":
    asyncio.run(main())
