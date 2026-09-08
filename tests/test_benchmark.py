"""离线任务队列基准测试。"""

import json

from corecoder.benchmark import (
    main,
    run_queue_benchmark,
    run_queue_benchmark_suite,
    write_benchmark_report,
    write_benchmark_suite_report,
)


def test_queue_benchmark_checks_concurrency_and_idempotency():
    result = run_queue_benchmark(task_count=30, worker_count=4)

    assert result.passed is True
    assert result.completed_tasks == 30
    assert result.duplicate_claims == 0
    assert result.idempotency_unique_tasks == 1
    assert result.processing_throughput_per_second > 0
    assert result.claim_latency_p95_ms >= result.claim_latency_p50_ms


def test_benchmark_report_is_machine_and_human_readable(tmp_path):
    result = run_queue_benchmark(task_count=10, worker_count=2)

    json_path, markdown_path = write_benchmark_report(result, tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["task_count"] == 10
    assert "Duplicate claims: 0" in markdown_path.read_text(encoding="utf-8")


def test_benchmark_cli_rejects_invalid_parameters(tmp_path, capsys):
    assert main(["--tasks", "0", "--output", str(tmp_path)]) == 2
    assert "参数错误" in capsys.readouterr().out


def test_repeated_benchmark_reports_distribution(tmp_path):
    results, summary = run_queue_benchmark_suite(task_count=10, worker_count=2, repetitions=3)

    assert len(results) == 3
    assert summary.all_passed is True
    assert summary.min_processing_throughput <= summary.median_processing_throughput
    assert summary.median_processing_throughput <= summary.max_processing_throughput

    json_path, markdown_path = write_benchmark_suite_report(results, summary, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(payload["runs"]) == 3
    assert "Throughput range" in markdown_path.read_text(encoding="utf-8")
