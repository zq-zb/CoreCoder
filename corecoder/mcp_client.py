"""MCP 客户端的最小实现：启动 stdio Server 并发现它提供的工具。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class DiscoveredTool:
    """CoreCoder 关心的 MCP 工具信息。
    这里不直接把 MCP SDK 的 Tool 对象传给其他模块。这样即使 SDK 将来
    调整内部类型，CoreCoder 也只需要修改这个文件里的转换逻辑。
    """

    name: str
    description: str
    input_schema: dict


async def discover_stdio_tools(
    command: str,
    args: list[str] | None = None,
) -> list[DiscoveredTool]:
    """启动一个 stdio MCP Server，并返回它公开的工具列表。

    Args:
        command: 启动 Server 的可执行程序，例如 ``python``、``node`` 或 ``npx``。
        args: 传给可执行程序的参数，例如 Python Server 脚本的路径。

    ``StdioServerParameters`` 只描述“如何启动进程”，此时连接还没有发生。
    进入 ``async with Client(...)`` 后，SDK 才会启动子进程、建立管道并完成
    MCP 协议握手；离开代码块时，连接和子进程会被自动关闭。
    """
    # 启动说明书
    server = StdioServerParameters(command=command, args=args or [])
    transport = stdio_client(server) # 发送请求
    # async 异步资源管理使用
    async with Client(transport) as client: # 启动、连接握手
        response = await client.list_tools()

        # MCP Server 返回完整的工具定义。先转换成 CoreCoder 自己的小数据结构，
        # 下一阶段再把它适配为 tools/base.py 中的 Tool。
        return [
            DiscoveredTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema),
            )
            for tool in response.tools
        ]


def main() -> None:
    """提供一个独立命令，方便先观察 MCP，而不改动 Agent 主循环。"""

    parser = argparse.ArgumentParser(description="启动 stdio MCP Server 并列出工具")
    parser.add_argument("command", help="Server 启动命令，例如 python、node 或 npx")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="传给 Server 的参数")
    options = parser.parse_args()

    # 用户写 ``python`` 时，优先复用当前解释器。这样从虚拟环境启动
    # CoreCoder 后，子进程也能看到同一环境里安装的 mcp 包。
    command = sys.executable if options.command == "python" else options.command
    tools = asyncio.run(discover_stdio_tools(command, options.args))
    if not tools:
        print("Server 没有公开任何工具。")
        return

    print(f"发现 {len(tools)} 个 MCP 工具：")
    for tool in tools:
        print(f"- {tool.name}: {tool.description}")
        print(f"  参数 Schema: {tool.input_schema}")


if __name__ == "__main__":
    main()
