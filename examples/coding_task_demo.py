"""离线演示 Coding Agent 如何根据测试失败自动修复并重新验证。"""

import sys
import tempfile
from pathlib import Path

from corecoder.agent import Agent
from corecoder.coding_task import CodingTaskRunner
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.shell_command import command_in_directory
from corecoder.tools import get_tool


def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="corecoder-coding-task-"))
    source = workspace / "calculator.py"
    test_file = workspace / "test_calculator.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    test_file.write_text(
        "import unittest\nfrom calculator import add\n\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    # -B 避免极快修改且文件大小不变时，下一个 Python 进程命中旧 .pyc。
    test_command = command_in_directory(workspace, [sys.executable, "-B", "-m", "pytest", test_file.name, "-q"])

    script = [
        LLMResponse(content="先读取问题代码。", tool_calls=[ToolCall("1", "read_file", {"file_path": str(source)})]),
        LLMResponse(content="先复现问题。", tool_calls=[ToolCall("2", "bash", {"command": test_command})]),
        LLMResponse(
            content="失败显示加法被写成了减法，执行最小修改。",
            tool_calls=[ToolCall("3", "edit_file", {
                "file_path": str(source),
                "old_string": "    return a - b",
                "new_string": "    return a + b",
            })],
        ),
        LLMResponse(content="重新运行同一测试。", tool_calls=[ToolCall("4", "bash", {"command": test_command})]),
        LLMResponse(content="add 已修复，最新修改已通过测试。"),
    ]
    agent = Agent(
        ScriptedLLM(script),
        tools=[get_tool("read_file"), get_tool("edit_file"), get_tool("bash")],
    )
    report = CodingTaskRunner(agent, workspace).run(
        "修复 calculator.py 中的 add 函数，并运行测试验证。",
        on_tool=lambda name, arguments: print(f"调用工具: {name} {arguments}"),
    )

    print(f"最终状态: {report.state.value}")
    print(f"修改文件: {list(report.changed_files)}")
    print(f"测试结果: {[run.passed for run in report.test_runs]}")
    print(f"最终说明: {report.final_response}")


if __name__ == "__main__":
    main()
