"""用于验证 MCP Server 进程突然退出时的传输故障处理。"""

import os

from mcp.server import MCPServer

mcp = MCPServer("corecoder-crash-test")


@mcp.tool()
def crash() -> str:
    """不返回 MCP 响应，直接模拟 Server 进程崩溃。"""

    os._exit(7)


if __name__ == "__main__":
    mcp.run()
