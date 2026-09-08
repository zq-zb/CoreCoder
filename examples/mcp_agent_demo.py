"""离线演示 Agent 动态发现并调用真实 MCP 工具。"""

import logging
import sys
from pathlib import Path

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.mcp_runtime import MCPRuntime
from corecoder.tools.mcp import create_mcp_tool_adapters


def main() -> None:
    """使用 ScriptedLLM 观察 Agent 的两轮工具调用循环。"""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server_path = Path(__file__).with_name("mcp_demo_server.py")
    runtime = MCPRuntime()

    print("1. Runtime 连接真实 MCP Server", flush=True)
    runtime.connect(sys.executable, [str(server_path)])

    try:
        mcp_tools = create_mcp_tool_adapters(runtime)
        print(f"2. 动态发现并适配工具：{[tool.name for tool in mcp_tools]}", flush=True)

        # 第一轮模拟 LLM 选择 add；第二轮模拟 LLM 根据工具结果生成最终回答。
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

        print("3. 用户向 Agent 提问：请计算 2 + 3", flush=True)
        answer = agent.chat(
            "请计算 2 + 3",
            on_tool=lambda name, arguments: print(
                f"4. LLM 选择工具：{name}，参数：{arguments}",
                flush=True,
            ),
        )
        print(f"5. Agent 最终回答：{answer}", flush=True)
    finally:
        runtime.close()
        print("6. Runtime 已关闭", flush=True)


if __name__ == "__main__":
    main()
