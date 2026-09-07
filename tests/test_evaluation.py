"""Coding Agent 评测集、隐藏验收、作用域和报告测试。"""

import json
import os
import subprocess
import sys
from pathlib import Path

from corecoder.agent import Agent
from corecoder.evaluation import (
    CodingAgentEvaluator,
    EvaluationFailure,
    build_evaluation_metadata,
    discover_cases,
    summarize_results,
    summarize_stability,
    write_evaluation_report,
)
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.tools import get_tool

CASES_ROOT = Path(__file__).parents[1] / "evals" / "cases"


def _visible_test_command(workspace: Path, filename: str) -> str:
    return f'cd /d "{workspace}" && "{sys.executable}" -B -m pytest "{filename}" -q'


def _calculator_agent(case, workspace: Path, *, write_extra: bool = False) -> Agent:
    source = workspace / "calculator.py"
    turns = [
        LLMResponse(tool_calls=[ToolCall("read", "read_file", {"file_path": str(source)})]),
        LLMResponse(tool_calls=[ToolCall("edit", "edit_file", {
            "file_path": str(source),
            "old_string": "    return a - b",
            "new_string": "    return a + b",
        })]),
    ]
    if write_extra:
        turns.append(
            LLMResponse(tool_calls=[ToolCall("extra", "write_file", {
                "file_path": str(workspace / "notes.txt"),
                "content": "unexpected\n",
            })])
        )
    turns.extend([
        LLMResponse(tool_calls=[ToolCall("test", "bash", {
            "command": _visible_test_command(workspace, "test_calculator.py"),
        })]),
        LLMResponse(content="已修复并通过测试。"),
    ])
    return Agent(
        ScriptedLLM(turns),
        tools=[get_tool("read_file"), get_tool("edit_file"), get_tool("write_file"), get_tool("bash")],
    )


def test_dataset_contains_fifteen_valid_cases_with_initially_failing_acceptance_tests():
    cases = discover_cases(CASES_ROOT)

    assert len(cases) == 15
    assert len({case.case_id for case in cases}) == 15
    for case in cases:
        environment = {**os.environ, "PYTHONPATH": str(case.workspace_dir)}
        command = [
            value.replace("{python}", sys.executable).replace("{case_dir}", str(case.case_dir))
            for value in case.verification.command
        ]
        completed = subprocess.run(
            command,
            cwd=case.workspace_dir,
            env=environment,
            check=False,
            capture_output=True,
            timeout=case.verification.timeout,
        )
        assert completed.returncode != 0, f"{case.case_id} 的初始 Bug 没有被隐藏测试捕获"


def test_evaluator_independently_verifies_success_and_collects_metrics():
    case = discover_cases(CASES_ROOT)[0]
    evaluator = CodingAgentEvaluator(lambda selected, workspace: _calculator_agent(selected, workspace))

    result = evaluator.run_case(case)

    assert result.success is True
    assert result.task_failure_reason is None
    assert result.task_events
    assert result.tool_trace == ("read_file", "edit_file", "bash")
    assert result.hidden_tests_passed is True
    assert result.changed_files == ("calculator.py",)
    assert result.tool_calls == 3
    assert result.failed_test_runs == 0
    assert result.duration_seconds > 0
    assert result.context_compressions == 0
    assert result.context_tokens_saved == 0


def test_stability_summary_distinguishes_flaky_case():
    case = discover_cases(CASES_ROOT)[0]
    evaluator = CodingAgentEvaluator(lambda selected, workspace: _calculator_agent(selected, workspace))
    passed = evaluator.run_case(case)
    flaky_copy = type(passed)(**{**passed.__dict__, "success": False})

    stability = summarize_stability([passed, flaky_copy])

    assert stability[0].runs == 2
    assert stability[0].passes == 1
    assert stability[0].pass_rate == 0.5


def test_evaluator_detects_unexpected_file_from_filesystem_diff():
    case = discover_cases(CASES_ROOT)[0]
    evaluator = CodingAgentEvaluator(
        lambda selected, workspace: _calculator_agent(selected, workspace, write_extra=True)
    )

    result = evaluator.run_case(case)

    assert result.hidden_tests_passed is True
    assert result.success is False
    assert result.unexpected_files == ("notes.txt",)
    assert EvaluationFailure.UNEXPECTED_FILE_CHANGE in result.failures


def test_evaluation_report_contains_json_and_markdown_summary(tmp_path):
    case = discover_cases(CASES_ROOT)[0]
    result = CodingAgentEvaluator(lambda selected, workspace: _calculator_agent(selected, workspace)).run_case(case)
    results, summary = [result], summarize_results([result])

    json_path, markdown_path = write_evaluation_report(results, summary, tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["success_rate"] == 1.0
    assert payload["results"][0]["case_id"] == "calculator-sign"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Success rate: 100.0%" in markdown
    assert "calculator-sign" in markdown


def test_metadata_fingerprint_is_stable_and_written_to_report(tmp_path):
    cases = discover_cases(CASES_ROOT)
    first = build_evaluation_metadata(cases, model="demo", provider="offline", strategy="baseline")
    second = build_evaluation_metadata(cases, model="demo", provider="offline", strategy="baseline")

    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert len(first.dataset_fingerprint) == 16

    result = CodingAgentEvaluator(lambda selected, workspace: _calculator_agent(selected, workspace)).run_case(cases[0])
    json_path, _ = write_evaluation_report([result], summarize_results([result]), tmp_path, metadata=first)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["strategy"] == "baseline"
    assert payload["metadata"]["dataset_fingerprint"] == first.dataset_fingerprint


def test_agent_factory_failure_becomes_result_instead_of_crashing_suite():
    case = discover_cases(CASES_ROOT)[0]

    def broken_factory(selected, workspace):
        raise RuntimeError("模型配置缺失")

    result = CodingAgentEvaluator(broken_factory).run_case(case)

    assert result.success is False
    assert result.failures == (EvaluationFailure.AGENT_FAILED,)
    assert result.tool_calls == 0
    assert "模型配置缺失" in result.agent_response
