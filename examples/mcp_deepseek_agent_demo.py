"""使用真实 DeepSeek 模型自主选择并调用 MCP 工具。"""

import logging
import sys
from pathlib import Path

from corecoder.agent import Agent
from corecoder.config import Config
from corecoder.llm import LLM
from corecoder.mcp_runtime import MCPRuntime
from corecoder.tools.mcp import create_mcp_tool_adapters


def run_case(llm: LLM, mcp_tools: list, question: str) -> None:
    """运行一个真实选择案例，并显示模型是否调用了工具。"""

    selected_tools: list[str] = []

    def show_tool(name: str, arguments: dict) -> None:
        selected_tools.append(name)
        print(f"   DeepSeek 选择工具：{name}，参数：{arguments}", flush=True)

    agent = Agent(llm=llm, tools=mcp_tools)
    print(f"\n用户问题：{question}", flush=True)
    answer = agent.chat(question, on_tool=show_tool)
    if not selected_tools:
        print("   DeepSeek 未调用工具", flush=True)
    print(f"   最终回答：{answer}", flush=True)


def main() -> None:
    """验证 DeepSeek 能选择不同 MCP 工具，也能选择不调用工具。"""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config.from_env()
    if not config.api_key:
        raise RuntimeError("未配置 DeepSeek API Key")

    llm = LLM(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    server_path = Path(__file__).with_name("mcp_demo_server.py")
    runtime = MCPRuntime()

    print(f"1. 使用真实模型：{config.model}", flush=True)
    runtime.connect(sys.executable, [str(server_path)])

    try:
        mcp_tools = create_mcp_tool_adapters(runtime)
        print(f"2. 提供给模型的 MCP 工具：{[tool.name for tool in mcp_tools]}", flush=True)

        cases = [
            "请使用合适的工具计算 12 + 30，并告诉我结果。",
            "请使用合适的工具向小明问好。",
            "不要调用任何工具，请用一句话介绍你自己。",
        ]
        for question in cases:
            run_case(llm, mcp_tools, question)

        print(
            f"\n3. Token 合计：输入 {llm.total_prompt_tokens}，输出 {llm.total_completion_tokens}",
            flush=True,
        )
        if llm.estimated_cost is not None:
            print(f"4. 估算费用：${llm.estimated_cost:.6f}", flush=True)
    finally:
        runtime.close()
        print("5. Runtime 已关闭", flush=True)


if __name__ == "__main__":
    main()
