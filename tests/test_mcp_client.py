"""MCP 客户端第一阶段测试：通过 stdio 发现工具。"""

import asyncio
import sys
from pathlib import Path

from corecoder.mcp_client import discover_stdio_tools


def test_discovers_tools_from_stdio_server():
    """客户端应能启动真实子进程，并读取 Server 返回的工具定义。"""

    server_path = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"
    tools = asyncio.run(discover_stdio_tools(sys.executable, [str(server_path)]))

    assert len(tools) == 2

    # 不依赖 Server 返回工具的先后顺序，通过名称找到我们要检查的工具。
    tools_by_name = {tool.name: tool for tool in tools}

    add = tools_by_name["add"]
    assert add.description == "把两个整数相加。"
    assert set(add.input_schema["properties"]) == {"a", "b"}
    assert set(add.input_schema["required"]) == {"a", "b"}

    greet = tools_by_name["greet"]
    assert greet.description == "根据名字生成一句中文问候语。"
    assert greet.input_schema["properties"]["name"]["type"] == "string"
    assert greet.input_schema["required"] == ["name"]
