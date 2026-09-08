import json

from corecoder.evaluation_compare import compare_evaluation_reports, write_comparison_report


def _report(strategy: str, *, searches: int = 0, fingerprint: str = "same") -> dict:
    return {
        "metadata": {
            "model": "demo",
            "provider": "offline",
            "dataset_fingerprint": fingerprint,
            "strategy": strategy,
        },
        "summary": {
            "total_cases": 1,
            "success_rate": 1.0,
            "hidden_test_pass_rate": 1.0,
            "average_tool_calls": 10.0,
            "average_duration_seconds": 2.0,
            "total_prompt_tokens": 100,
            "total_completion_tokens": 20,
            "total_repository_search_calls": searches,
            "total_retrieval_policy_rejections": 1 if "guided" in strategy else 0,
            "total_estimated_cost": None,
        },
        "results": [{
            "case_id": "demo",
            "tool_trace": ["bash", "repository_search"] if "guided" in strategy else [],
        }],
    }


def test_comparison_warns_when_retrieval_was_not_exercised() -> None:
    result = compare_evaluation_reports(
        _report("structured-memory+retrieval-off"),
        _report("structured-memory+retrieval-on"),
    )

    assert result.comparable is True
    assert any("没有实际调用" in warning for warning in result.warnings)
    assert any("少于 3 次" in warning for warning in result.warnings)


def test_comparison_rejects_mismatched_dataset() -> None:
    result = compare_evaluation_reports(
        _report("retrieval-off", fingerprint="a"),
        _report("retrieval-on", searches=1, fingerprint="b"),
    )

    assert result.comparable is False
    assert any("dataset_fingerprint" in warning for warning in result.warnings)


def test_comparison_infers_rejections_from_legacy_guided_trace() -> None:
    result = compare_evaluation_reports(
        _report("retrieval-off"),
        _report("retrieval-guided", searches=1),
    )

    assert result.candidate_retrieval_policy_rejections == 1


def test_comparison_writes_sanitized_reports(tmp_path) -> None:
    result = compare_evaluation_reports(_report("retrieval-off"), _report("retrieval-on", searches=1))

    json_path, markdown_path = write_comparison_report(result, tmp_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["candidate_repository_search_calls"] == 1
    assert "Evidence warnings" in markdown_path.read_text(encoding="utf-8")
