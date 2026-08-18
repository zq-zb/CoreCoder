"""供第一阶段学习使用的最小 stdio MCP Server。"""

from mcp.server import MCPServer

# 创建 Server 对象
mcp = MCPServer("corecoder-demo")

# MCP 工具 注册工具
@mcp.tool()  # 加入到清单
def add(a: int, b: int) -> int:
    """把两个整数相加。"""

    return a + b


@mcp.tool()
def greet(name: str) -> str:
    """根据名字生成一句中文问候语。"""

    return f"你好，{name}！"


if __name__ == "__main__":
    # 不传 transport 时默认使用 stdio。这个进程启动后会等待 Client 从
    # stdin 发来 JSON-RPC 请求，并把响应写入 stdout。
    mcp.run() # MCP Server 启动后一直不退出
