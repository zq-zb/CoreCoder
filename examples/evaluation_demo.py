"""不调用真实模型，演示一条完整的 Coding Agent 评测链路。"""

import sys
from pathlib import Path

from corecoder.agent import Agent
from corecoder.evaluation import CodingAgentEvaluator, discover_cases, write_evaluation_report
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.shell_command import command_in_directory
from corecoder.tools import get_tool

ROOT = Path(__file__).parents[1]


def create_demo_agent(case, workspace: Path) -> Agent:
    """用固定回复模拟 Agent，便于只观察评测系统本身。"""

    source = workspace / "calculator.py"
    visible_test = workspace / "test_calculator.py"
    responses = [
        LLMResponse(tool_calls=[ToolCall("read", "read_file", {"file_path": str(source)})]),
        LLMResponse(
            tool_calls=[
                ToolCall(
                    "edit",
                    "edit_file",
                    {
                        "file_path": str(source),
                        "old_string": "    return a - b",
                        "new_string": "    return a + b",
                    },
                )
            ]
        ),
        LLMResponse(
            tool_calls=[
                ToolCall(
                    "test",
                    "bash",
                    {
                        "command": command_in_directory(
                            workspace,
                            [sys.executable, "-B", "-m", "pytest", visible_test.name, "-q"],
                        )
                    },
                )
            ]
        ),
        LLMResponse(content="修复完成，可见测试通过。"),
    ]
    return Agent(
        ScriptedLLM(responses),
        tools=[get_tool("read_file"), get_tool("edit_file"), get_tool("bash")],
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    case = next(case for case in discover_cases(ROOT / "evals" / "cases") if case.case_id == "calculator-sign")
    results, summary = CodingAgentEvaluator(create_demo_agent).run_suite([case])
    json_path, markdown_path = write_evaluation_report(results, summary, ROOT / "evals" / "reports" / "demo")
    print(f"评测结果：{summary.passed_cases}/{summary.total_cases}")
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")


if __name__ == "__main__":
    main()
