"""Agent 通过 Runtime 调用真实 MCP 工具的端到端测试。"""

import sys
from pathlib import Path

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.mcp_runtime import MCPRuntime
from corecoder.tools.mcp import create_mcp_tool_adapters

SERVER_PATH = Path(__file__).parents[1] / "examples" / "mcp_demo_server.py"


def test_agent_executes_dynamically_discovered_mcp_tool():
    """Agent 应执行 LLM 选择的真实 MCP 工具，并把结果写回对话。"""

    runtime = MCPRuntime()
    runtime.connect(sys.executable, [str(SERVER_PATH)])

    try:
        mcp_tools = create_mcp_tool_adapters(runtime)
        llm = ScriptedLLM(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="mcp-call-1",
                            name="add",
                            arguments={"a": 2, "b": 3},
                        )
                    ]
                ),
                LLMResponse(content="计算结果是 5。"),
            ]
        )
        agent = Agent(llm=llm, tools=mcp_tools)

        answer = agent.chat("请计算 2 + 3")
    finally:
        runtime.close()

    assert answer == "计算结果是 5。"
    assert {tool.name for tool in mcp_tools} == {"add", "greet"}
    assert any(message.get("role") == "tool" and message.get("content") == "5" for message in agent.messages)
