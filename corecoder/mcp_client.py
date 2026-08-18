"""MCP 客户端的最小实现：启动 stdio Server、发现并调用它提供的工具。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


@dataclass(frozen=True)
class DiscoveredTool:
    """CoreCoder 关心的 MCP 工具信息。
    这里不直接把 MCP SDK 的 Tool 对象传给其他模块。这样即使 SDK 将来
    调整内部类型，CoreCoder 也只需要修改这个文件里的转换逻辑。
    """

    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class MCPToolCallResult:
    """CoreCoder 统一后的 MCP 工具调用结果。

    ``text`` 适合直接显示或写入 Agent 对话历史；``is_error`` 用来区分
    “协议调用成功但工具执行失败”；``structured_content`` 则保留 Server
    可能返回的结构化数据，避免在文本转换时丢失信息。
    """

    text: str
    is_error: bool
    structured_content: Any | None = None


def _content_to_text(content: list[Any]) -> str:
    """把 MCP 内容块转换成当前文本型 Agent 可以消费的字符串。"""

    parts: list[str] = []
    for item in content:
        if isinstance(item, TextContent):
            parts.append(item.text)
        else:
            # 当前 CoreCoder 还是纯文本 Agent。遇到图片、音频或资源时先留下
            # 类型提示；后续实现多模态消息时可以在这里增加专门的转换逻辑。
            parts.append(f"[暂不支持的 MCP 内容类型: {item.type}]")
    return "\n".join(parts)


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


async def call_stdio_tool(
    command: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    args: list[str] | None = None,
) -> MCPToolCallResult:
    """启动 stdio MCP Server，调用一个工具并返回统一后的结果。

    连接生命周期与工具发现保持一致：进入 ``async with`` 时启动并握手，
    调用结束或发生异常后退出代码块，SDK 会负责关闭连接和 Server 子进程。

    Args:
        command: 启动 Server 的可执行程序。
        name: MCP Server 中注册的工具名称。
        arguments: 传给工具的参数，键和值必须符合工具的 inputSchema。
        args: 传给 Server 可执行程序的启动参数。
    """

    server = StdioServerParameters(command=command, args=args or [])
    transport = stdio_client(server)
    async with Client(transport) as client:
        response = await client.call_tool(name=name, arguments=arguments or {})

    return MCPToolCallResult(
        text=_content_to_text(response.content),
        is_error=response.is_error,
        structured_content=response.structured_content,
    )


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
