"""用于验证只对明确安全的瞬时错误执行重试。"""

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

mcp = MCPServer("corecoder-retry-test")
attempts = 0


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def flaky_read() -> CallToolResult:
    """第一次返回可重试错误，第二次成功。"""

    global attempts
    attempts += 1
    if attempts == 1:
        return CallToolResult(
            content=[TextContent(type="text", text="临时依赖不可用")],
            structured_content={"retryable": True},
            is_error=True,
        )
    return CallToolResult(
        content=[TextContent(type="text", text="读取成功")],
        structured_content={"attempts": attempts},
    )


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def always_transient_error() -> CallToolResult:
    """持续返回可重试错误，用于验证熔断器。"""

    return CallToolResult(
        content=[TextContent(type="text", text="上游服务持续不可用")],
        structured_content={"retryable": True},
        is_error=True,
    )


if __name__ == "__main__":
    mcp.run()
