import json

from corecoder.evaluation import discover_cases
from corecoder.retrieval_benchmark import (
    main,
    run_retrieval_benchmark,
    write_retrieval_benchmark_report,
)


def test_retrieval_benchmark_measures_labeled_cross_file_cases() -> None:
    cases = discover_cases("evals/cases")

    results, summary = run_retrieval_benchmark(cases)

    assert [result.case_id for result in results] == ["discount-call-chain", "pagination-empty-page"]
    assert summary.cases == 2
    assert 0 <= summary.average_context_recall_at_1 <= summary.average_context_recall_at_3
    assert summary.average_context_recall_at_3 <= summary.average_context_recall_at_5 <= 1
    assert summary.mean_reciprocal_rank > 0
    assert all(result.duration_seconds > 0 for result in results)


def test_retrieval_benchmark_writes_machine_and_human_reports(tmp_path) -> None:
    results, summary = run_retrieval_benchmark(discover_cases("evals/cases"))

    json_path, markdown_path = write_retrieval_benchmark_report(results, summary, tmp_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["cases"] == 2
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Context recall @1/@3/@5" in markdown
    assert "pagination-empty-page" in markdown


def test_retrieval_benchmark_cli_returns_failure_without_labeled_cases(tmp_path) -> None:
    empty_cases = tmp_path / "cases"
    empty_cases.mkdir()

    assert main(["--cases", str(empty_cases), "--output", str(tmp_path / "report")]) == 1
