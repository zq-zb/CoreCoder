"""专门用于验证 MCP 工具调用超时的测试 Server。"""

import time

from mcp.server import MCPServer

mcp = MCPServer("corecoder-slow-test")


@mcp.tool()
def slow_echo(text: str, delay: float = 0.2) -> str:
    """等待指定时间后返回文本，用于模拟响应缓慢的外部工具。"""

    time.sleep(delay)
    return text


if __name__ == "__main__":
    mcp.run()
