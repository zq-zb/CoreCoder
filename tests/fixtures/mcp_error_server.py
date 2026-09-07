"""用于验证工具执行错误不会破坏 MCP 连接的测试 Server。"""

from mcp.server import MCPServer

mcp = MCPServer("corecoder-error-test")


@mcp.tool()
def fail_operation(reason: str) -> str:
    """模拟一个明确执行失败的业务工具。"""

    raise ValueError(f"业务操作失败：{reason}")


@mcp.tool()
def echo(text: str) -> str:
    """用于验证失败后的同一连接仍然可用。"""

    return text


if __name__ == "__main__":
    mcp.run()
