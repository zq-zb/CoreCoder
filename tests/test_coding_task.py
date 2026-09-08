"""Coding Agent 代码修改、测试反馈和有限修复闭环测试。"""

import sys

from corecoder.agent import Agent
from corecoder.coding_task import CodingTaskRunner, CodingTaskState
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.shell_command import command_in_directory
from corecoder.tools import get_tool


def _test_command(test_file) -> str:
    return command_in_directory(test_file.parent, [sys.executable, "-B", "-m", "pytest", test_file.name, "-q"])


def test_coding_task_repairs_failure_and_verifies_latest_edit(tmp_path):
    """Agent 应读取代码、观察失败、修复并通过第二次测试。"""

    source = tmp_path / "calculator.py"
    test_file = tmp_path / "test_calculator.py"
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    test_file.write_text(
        "import unittest\nfrom calculator import add\n\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    command = _test_command(test_file)
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall("read", "read_file", {"file_path": str(source)})]),
            LLMResponse(tool_calls=[ToolCall("test-1", "bash", {"command": command})]),
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
            LLMResponse(tool_calls=[ToolCall("test-2", "bash", {"command": command})]),
            LLMResponse(content="已修复 add 并通过测试。"),
        ]
    )
    agent = Agent(llm, tools=[get_tool("read_file"), get_tool("edit_file"), get_tool("bash")])

    report = CodingTaskRunner(agent, tmp_path).run("修复 add 函数")

    assert report.state is CodingTaskState.COMPLETED
    assert report.verified is True
    assert [run.passed for run in report.test_runs] == [False, True]
    assert report.changed_files == (str(source.resolve()),)
    assert "return a + b" in source.read_text(encoding="utf-8")
    assert [event.state for event in report.events] == [
        CodingTaskState.FIXING,
        CodingTaskState.FIXING,
        CodingTaskState.TESTING,
    ]


def test_coding_task_rejects_unverified_final_edit(tmp_path):
    """最后一次修改后没有测试，即使 LLM 声称完成也应标记失败。"""

    source = tmp_path / "value.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "edit",
                        "edit_file",
                        {"file_path": str(source), "old_string": "VALUE = 1", "new_string": "VALUE = 2"},
                    )
                ]
            ),
            LLMResponse(content="已完成。"),
        ]
    )
    agent = Agent(llm, tools=[get_tool("edit_file")])

    report = CodingTaskRunner(agent, tmp_path).run("修改 VALUE")

    assert report.state is CodingTaskState.FAILED
    assert report.verified is False
    assert report.failure_reason == "最后一次代码修改后没有通过测试"


def test_coding_task_stops_after_fix_attempt_limit(tmp_path):
    """连续测试失败超限后应有限结束，不继续消耗 LLM 轮次。"""

    test_file = tmp_path / "test_always_fails.py"
    test_file.write_text(
        "import unittest\n\nclass AlwaysFails(unittest.TestCase):\n"
        "    def test_nope(self):\n        self.fail('still broken')\n",
        encoding="utf-8",
    )
    command = _test_command(test_file)
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall("test-1", "bash", {"command": command})]),
            LLMResponse(tool_calls=[ToolCall("test-2", "bash", {"command": command})]),
            LLMResponse(content="这一轮不应被消费。"),
        ]
    )
    agent = Agent(llm, tools=[get_tool("bash")])

    report = CodingTaskRunner(agent, tmp_path, max_fix_attempts=1).run("修复测试")

    assert report.state is CodingTaskState.FAILED
    assert len(report.test_runs) == 2
    assert "超过最大自动修复次数" in report.failure_reason


def test_coding_task_blocks_file_edit_outside_workspace(tmp_path):
    """Coding Task 不应允许文件工具越过指定工作区。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall("edit", "edit_file", {
                "file_path": str(outside),
                "old_string": "VALUE = 1",
                "new_string": "VALUE = 2",
            })]),
            LLMResponse(content="已停止。"),
        ]
    )
    agent = Agent(llm, tools=[get_tool("edit_file")])

    report = CodingTaskRunner(agent, workspace).run("修改工作区外文件")

    assert outside.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert report.changed_files == ()
    assert "outside coding workspace" in agent.messages[-2]["content"]


def test_coding_evaluation_mode_requires_an_actual_change(tmp_path):
    """修复型评测不能把“无修改、无测试”的空操作算作成功。"""

    agent = Agent(ScriptedLLM([LLMResponse(content="无需修改。")]), tools=[])

    report = CodingTaskRunner(agent, tmp_path, require_changes=True).run("修复已知缺陷")

    assert report.state is CodingTaskState.FAILED
    assert report.failure_reason == "任务要求修改代码，但未检测到文件变更"


def test_workspace_guards_preserve_guided_retrieval_prompt(tmp_path):
    """安装安全守卫不能让提示层和 guided 执行策略失去同步。"""

    agent = Agent(
        ScriptedLLM([LLMResponse(content="unused")]),
        tools=[get_tool("repository_search"), get_tool("read_file")],
        repository_retrieval_policy="guided",
    )

    CodingTaskRunner(agent, tmp_path)

    assert "Guided retrieval policy" in agent._system
    assert "runtime enforces this ordering" in agent._system


def test_state_machine_stops_after_modified_code_passes_test(tmp_path):
    """评测模式由状态机收敛，不要求模型再额外返回结束文本。"""

    source = tmp_path / "value.py"
    test_file = tmp_path / "test_value.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test_file.write_text("from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n", encoding="utf-8")
    command = _test_command(test_file)
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("edit", "edit_file", {
            "file_path": str(source), "old_string": "VALUE = 1", "new_string": "VALUE = 2",
        })]),
        LLMResponse(tool_calls=[ToolCall("test", "bash", {"command": command})]),
        LLMResponse(tool_calls=[ToolCall("redundant", "read_file", {"file_path": str(source)})]),
    ])
    agent = Agent(llm, tools=[get_tool("edit_file"), get_tool("read_file"), get_tool("bash")])

    report = CodingTaskRunner(
        agent,
        tmp_path,
        require_changes=True,
        stop_after_verified=True,
    ).run("修改并验证 VALUE")

    assert report.state is CodingTaskState.COMPLETED
    assert report.verified is True
    assert "状态机" in report.final_response
    assert all(call.get("tool_call_id") != "redundant" for call in agent.messages)


def test_passed_test_adds_soft_convergence_feedback(tmp_path):
    source = tmp_path / "value.py"
    test_file = tmp_path / "test_value.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test_file.write_text("from value import VALUE\n\ndef test_value():\n    assert VALUE == 2\n", encoding="utf-8")
    command = _test_command(test_file)
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("edit", "edit_file", {
            "file_path": str(source), "old_string": "VALUE = 1", "new_string": "VALUE = 2",
        })]),
        LLMResponse(tool_calls=[ToolCall("test", "bash", {"command": command})]),
        LLMResponse(content="完成。"),
    ])
    agent = Agent(llm, tools=[get_tool("edit_file"), get_tool("bash")])

    report = CodingTaskRunner(agent, tmp_path, require_changes=True).run("修改 VALUE")

    assert report.state is CodingTaskState.COMPLETED
    test_reply = next(message for message in agent.messages if message.get("tool_call_id") == "test")
    assert "CoreCoder control" in test_reply["content"]
    assert "立即返回最终总结" in test_reply["content"]
