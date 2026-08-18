"""MCP 客户端集成测试：通过 stdio 发现并调用工具。"""

import asyncio
import sys
from pathlib import Path

import pytest

from corecoder.mcp_client import PersistentMCPClient, call_stdio_tool, discover_stdio_tools

SERVER_PATH = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"


def test_persistent_client_opens_and_closes_connection():
    """持久化 Client 离开 async with 后必须释放连接和 Server 子进程。"""

    async def run_scenario():
        client = PersistentMCPClient(sys.executable, [str(SERVER_PATH)])

        assert client._client is None
        async with client:
            assert client._client is not None

        assert client._client is None
        assert client._exit_stack is None

    asyncio.run(run_scenario())


def test_persistent_client_close_is_idempotent():
    """重复关闭 Client 应安全返回，不应重复释放同一批资源。"""

    async def run_scenario():
        client = PersistentMCPClient(sys.executable, [str(SERVER_PATH)])
        await client.connect()

        await client.close()
        await client.close()

        assert client._client is None
        assert client._exit_stack is None

    asyncio.run(run_scenario())


def test_persistent_client_closes_connection_after_context_error():
    """业务代码抛出异常时，async with 仍应释放连接和子进程。"""

    async def run_scenario():
        client = PersistentMCPClient(sys.executable, [str(SERVER_PATH)])

        with pytest.raises(RuntimeError, match="模拟业务失败"):
            async with client:
                assert client._client is not None
                raise RuntimeError("模拟业务失败")

        assert client._client is None
        assert client._exit_stack is None

    asyncio.run(run_scenario())


def test_persistent_client_requires_connection_before_listing_tools():
    """未连接时调用工具发现，应得到清晰的使用方式提示。"""

    client = PersistentMCPClient(sys.executable, [str(SERVER_PATH)])

    with pytest.raises(RuntimeError, match="尚未连接"):
        asyncio.run(client.list_tools())


def test_persistent_client_requires_connection_before_calling_tool():
    """未连接时调用工具，应得到清晰的使用方式提示。"""

    client = PersistentMCPClient(sys.executable, [str(SERVER_PATH)])

    with pytest.raises(RuntimeError, match="尚未连接"):
        asyncio.run(client.call_tool("add", {"a": 2, "b": 3}))


def test_persistent_client_lists_tools_on_existing_connection():
    """工具发现应复用已经建立的连接。"""

    async def run_scenario():
        async with PersistentMCPClient(sys.executable, [str(SERVER_PATH)]) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    assert asyncio.run(run_scenario()) == {"add", "greet"}


def test_persistent_client_reuses_connection_for_multiple_calls():
    """同一上下文中的多次工具调用应复用一个 MCP Client。"""

    async def run_scenario():
        async with PersistentMCPClient(sys.executable, [str(SERVER_PATH)]) as client:
            connected_client = client._client

            add_result = await client.call_tool("add", {"a": 2, "b": 3})
            greet_result = await client.call_tool("greet", {"name": "小明"})

            assert client._client is connected_client
            return add_result, greet_result

    add_result, greet_result = asyncio.run(run_scenario())

    assert add_result.text == "5"
    assert add_result.is_error is False
    assert greet_result.text == "你好，小明！"
    assert greet_result.is_error is False


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
