"""MCP 客户端第一阶段测试：通过 stdio 发现工具。"""

import asyncio
import sys
from pathlib import Path

from corecoder.mcp_client import call_stdio_tool, discover_stdio_tools

SERVER_PATH = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"


def test_discovers_tools_from_stdio_server():
    """客户端应能启动真实子进程，并读取 Server 返回的工具定义。"""

    tools = asyncio.run(discover_stdio_tools(sys.executable, [str(SERVER_PATH)]))

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


def test_calls_add_tool_over_stdio():
    """客户端应能把参数发送给真实 Server，并收到工具执行结果。"""

    result = asyncio.run(
        call_stdio_tool(
            sys.executable,
            "add",
            {"a": 2, "b": 3},
            [str(SERVER_PATH)],
        )
    )

    assert result.text == "5"
    assert result.is_error is False


def test_calls_greet_tool_with_chinese_text():
    """stdio 和 MCP 内容转换应正确保留中文。"""

    result = asyncio.run(
        call_stdio_tool(
            sys.executable,
            "greet",
            {"name": "小明"},
            [str(SERVER_PATH)],
        )
    )

    assert result.text == "你好，小明！"
    assert result.is_error is False


def test_reports_unknown_tool_as_business_error():
    """工具不存在属于业务执行失败，不应误判为连接失败。"""

    result = asyncio.run(
        call_stdio_tool(
            sys.executable,
            "missing_tool",
            {},
            [str(SERVER_PATH)],
        )
    )

    assert result.is_error is True
    assert result.text
