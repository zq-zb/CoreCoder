"""无需模型 API 的任务队列性能与并发正确性基线。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .task_store import TaskStatus, TaskStore


@dataclass(frozen=True)
class QueueBenchmarkResult:
    created_at_utc: str
    platform: str
    python_version: str
    sqlite_version: str
    task_count: int
    worker_count: int
    completed_tasks: int
    duplicate_claims: int
    idempotency_unique_tasks: int
    enqueue_throughput_per_second: float
    processing_throughput_per_second: float
    claim_latency_p50_ms: float
    claim_latency_p95_ms: float
    total_duration_seconds: float

    @property
    def passed(self) -> bool:
        return (
            self.completed_tasks == self.task_count
            and self.duplicate_claims == 0
            and self.idempotency_unique_tasks == 1
        )


@dataclass(frozen=True)
class QueueBenchmarkSummary:
    repetitions: int
    all_passed: bool
    median_processing_throughput: float
    min_processing_throughput: float
    max_processing_throughput: float
    median_claim_p95_ms: float
    worst_claim_p95_ms: float


def run_queue_benchmark(*, task_count: int = 200, worker_count: int = 8) -> QueueBenchmarkResult:
    """并发入队和消费固定数量任务，检查性能与 exactly-once claim。"""

    if task_count <= 0 or worker_count <= 0:
        raise ValueError("任务数和 Worker 数必须大于 0")
    with tempfile.TemporaryDirectory(prefix="corecoder-benchmark-") as directory:
        store = TaskStore(Path(directory) / "benchmark.db")
        total_started = time.perf_counter()
        enqueue_started = time.perf_counter()

        def enqueue(index: int) -> str:
            return store.enqueue(
                "benchmark",
                {"index": index},
                idempotency_key=f"benchmark-{index}",
            ).task_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            task_ids = list(pool.map(enqueue, range(task_count)))
        enqueue_duration = max(time.perf_counter() - enqueue_started, 1e-9)

        claimed_ids: list[str] = []
        claim_latencies: list[float] = []
        lock = threading.Lock()
        processing_started = time.perf_counter()

        def worker(index: int) -> None:
            worker_id = f"benchmark-worker-{index}"
            while True:
                started = time.perf_counter()
                task = store.claim_next(worker_id, lease_seconds=30)
                latency = (time.perf_counter() - started) * 1000
                if task is None:
                    return
                with lock:
                    claim_latencies.append(latency)
                    claimed_ids.append(task.task_id)
                store.finish(task.task_id, worker_id, succeeded=True, result={"benchmark": True})

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            list(pool.map(worker, range(worker_count)))
        processing_duration = max(time.perf_counter() - processing_started, 1e-9)

        # 模拟调用方对同一请求并发重试，数据库唯一约束应只生成一条任务。
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            retried = list(
                pool.map(
                    lambda _: store.enqueue("benchmark", {"kind": "retry"}, idempotency_key="retry-same"),
                    range(worker_count * 2),
                )
            )

        completed = sum(store.get(task_id).status is TaskStatus.SUCCEEDED for task_id in task_ids)
        duplicate_claims = len(claimed_ids) - len(set(claimed_ids))
        total_duration = time.perf_counter() - total_started
        return QueueBenchmarkResult(
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            platform=platform.platform(),
            python_version=platform.python_version(),
            sqlite_version=sqlite3.sqlite_version,
            task_count=task_count,
            worker_count=worker_count,
            completed_tasks=completed,
            duplicate_claims=duplicate_claims,
            idempotency_unique_tasks=len({task.task_id for task in retried}),
            enqueue_throughput_per_second=round(task_count / enqueue_duration, 2),
            processing_throughput_per_second=round(task_count / processing_duration, 2),
            claim_latency_p50_ms=round(_percentile(claim_latencies, 50), 3),
            claim_latency_p95_ms=round(_percentile(claim_latencies, 95), 3),
            total_duration_seconds=round(total_duration, 3),
        )


def write_benchmark_report(result: QueueBenchmarkResult, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "queue-benchmark.json"
    markdown_path = destination / "queue-benchmark.md"
    payload = {**asdict(result), "passed": result.passed}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(
        "\n".join([
            "# CoreCoder Queue Benchmark",
            "",
            f"- Result: {'PASS' if result.passed else 'FAIL'}",
            f"- Platform: {result.platform}",
            f"- Python/SQLite: {result.python_version}/{result.sqlite_version}",
            f"- Tasks: {result.completed_tasks}/{result.task_count}",
            f"- Workers: {result.worker_count}",
            f"- Enqueue throughput: {result.enqueue_throughput_per_second:.2f} tasks/s",
            f"- Processing throughput: {result.processing_throughput_per_second:.2f} tasks/s",
            f"- Claim latency P50/P95: {result.claim_latency_p50_ms:.3f}/{result.claim_latency_p95_ms:.3f} ms",
            f"- Duplicate claims: {result.duplicate_claims}",
            f"- Idempotency unique tasks: {result.idempotency_unique_tasks}",
            f"- Total duration: {result.total_duration_seconds:.3f}s",
            "",
        ]),
        encoding="utf-8",
    )
    return json_path, markdown_path


def run_queue_benchmark_suite(
    *, task_count: int = 200, worker_count: int = 8, repetitions: int = 3
) -> tuple[list[QueueBenchmarkResult], QueueBenchmarkSummary]:
    if repetitions <= 0:
        raise ValueError("重复次数必须大于 0")
    results = [
        run_queue_benchmark(task_count=task_count, worker_count=worker_count)
        for _ in range(repetitions)
    ]
    throughputs = [result.processing_throughput_per_second for result in results]
    p95_values = [result.claim_latency_p95_ms for result in results]
    return results, QueueBenchmarkSummary(
        repetitions=repetitions,
        all_passed=all(result.passed for result in results),
        median_processing_throughput=round(statistics.median(throughputs), 2),
        min_processing_throughput=round(min(throughputs), 2),
        max_processing_throughput=round(max(throughputs), 2),
        median_claim_p95_ms=round(statistics.median(p95_values), 3),
        worst_claim_p95_ms=round(max(p95_values), 3),
    )


def write_benchmark_suite_report(
    results: list[QueueBenchmarkResult],
    summary: QueueBenchmarkSummary,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "queue-benchmark-suite.json"
    markdown_path = destination / "queue-benchmark-suite.md"
    payload = {"summary": asdict(summary), "runs": [{**asdict(result), "passed": result.passed} for result in results]}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CoreCoder Queue Benchmark Suite",
        "",
        f"- Result: {'PASS' if summary.all_passed else 'FAIL'}",
        f"- Repetitions: {summary.repetitions}",
        f"- Median throughput: {summary.median_processing_throughput:.2f} tasks/s",
        f"- Throughput range: {summary.min_processing_throughput:.2f}–{summary.max_processing_throughput:.2f} tasks/s",
        f"- Median/Worst claim P95: {summary.median_claim_p95_ms:.3f}/{summary.worst_claim_p95_ms:.3f} ms",
        "",
        "| Run | Throughput | Claim P50 | Claim P95 | Duplicate claims | Passed |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for index, result in enumerate(results, 1):
        lines.append(
            f"| {index} | {result.processing_throughput_per_second:.2f} | "
            f"{result.claim_latency_p50_ms:.3f} | {result.claim_latency_p95_ms:.3f} | "
            f"{result.duplicate_claims} | {'yes' if result.passed else 'no'} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1))))
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="运行 CoreCoder 离线任务队列基准")
    parser.add_argument("--tasks", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/benchmark"))
    options = parser.parse_args(argv)
    try:
        results, summary = run_queue_benchmark_suite(
            task_count=options.tasks,
            worker_count=options.workers,
            repetitions=options.repeat,
        )
    except ValueError as error:
        print(f"基准参数错误：{error}")
        return 2
    json_path, markdown_path = write_benchmark_suite_report(results, summary, options.output)
    print(f"基准结果：{'PASS' if summary.all_passed else 'FAIL'}（{summary.repetitions} 轮）")
    print(f"处理吞吐中位数：{summary.median_processing_throughput:.2f} tasks/s")
    print(f"处理吞吐范围：{summary.min_processing_throughput:.2f}–{summary.max_processing_throughput:.2f} tasks/s")
    print(f"最差领取延迟 P95：{summary.worst_claim_p95_ms:.3f} ms")
    print(f"报告：{markdown_path.resolve()}（JSON: {json_path.resolve()}）")
    return 0 if summary.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
