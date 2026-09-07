"""用可控合成仓库测量检索延迟随文件数量的变化。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .tools.repository_search import RepositorySearchTool


@dataclass(frozen=True)
class RetrievalScalePoint:
    files: int
    cold_duration_ms: float
    average_warm_duration_ms: float
    warm_p95_duration_ms: float
    single_file_refresh_ms: float
    speedup: float


@dataclass(frozen=True)
class RetrievalScaleBenchmark:
    query: str
    repetitions: int
    points: tuple[RetrievalScalePoint, ...]


def run_scale_benchmark(
    file_counts: tuple[int, ...] = (100, 500, 1000, 3000),
    *,
    repetitions: int = 5,
) -> RetrievalScaleBenchmark:
    """生成不同规模的同构仓库，避免业务仓库内容差异污染趋势。"""

    if repetitions < 3:
        raise ValueError("repetitions 必须至少为 3，才能计算有意义的 P95")
    if not file_counts or any(count < 1 for count in file_counts):
        raise ValueError("file_counts 必须包含正整数")

    query = "critical_payment_handler"
    points: list[RetrievalScalePoint] = []
    with tempfile.TemporaryDirectory(prefix="corecoder-retrieval-scale-") as temporary:
        temporary_root = Path(temporary)
        for file_count in file_counts:
            repository = temporary_root / f"repository-{file_count}"
            _create_synthetic_repository(repository, file_count)
            tool = RepositorySearchTool()
            durations: list[float] = []
            for _ in range(repetitions):
                started = time.perf_counter()
                result = tool.execute(query, str(repository), limit=5)
                durations.append((time.perf_counter() - started) * 1000)
                if "critical_payment_handler.py" not in result:
                    raise RuntimeError("规模基准未检索到目标文件")
            warm = durations[1:]
            warm_average = statistics.mean(warm)
            target = repository / "critical_payment_handler.py"
            target.write_text(
                "def critical_payment_handler_v2(payment):\n    return payment\n",
                encoding="utf-8",
            )
            refresh_started = time.perf_counter()
            refreshed = tool.execute("critical_payment_handler_v2", str(repository), limit=5)
            refresh_duration = (time.perf_counter() - refresh_started) * 1000
            if "critical_payment_handler.py" not in refreshed:
                raise RuntimeError("增量刷新后未检索到修改文件")
            points.append(
                RetrievalScalePoint(
                    files=file_count,
                    cold_duration_ms=durations[0],
                    average_warm_duration_ms=warm_average,
                    warm_p95_duration_ms=_percentile(warm, 0.95),
                    single_file_refresh_ms=refresh_duration,
                    speedup=durations[0] / warm_average if warm_average else 0.0,
                )
            )
    return RetrievalScaleBenchmark(query=query, repetitions=repetitions, points=tuple(points))


def write_scale_benchmark_report(
    result: RetrievalScaleBenchmark,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "retrieval-scale-benchmark.json"
    markdown_path = destination / "retrieval-scale-benchmark.md"
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CoreCoder Retrieval Scale Benchmark",
        "",
        f"- Query: `{result.query}`",
        f"- Repetitions per size: {result.repetitions}",
        "",
        "| Files | Cold (ms) | Warm mean (ms) | Warm P95 (ms) | One-file refresh (ms) | Speedup |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for point in result.points:
        lines.append(
            f"| {point.files} | {point.cold_duration_ms:.2f} | "
            f"{point.average_warm_duration_ms:.2f} | {point.warm_p95_duration_ms:.2f} | "
            f"{point.single_file_refresh_ms:.2f} | {point.speedup:.2f}x |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Benchmark retrieval latency across repository sizes")
    parser.add_argument("--file-counts", default="100,500,1000,3000")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="evals/reports/retrieval-scale")
    args = parser.parse_args(argv)
    try:
        file_counts = tuple(int(value.strip()) for value in args.file_counts.split(",") if value.strip())
        result = run_scale_benchmark(file_counts, repetitions=args.repetitions)
    except ValueError as error:
        parser.error(str(error))
    json_path, markdown_path = write_scale_benchmark_report(result, args.output)
    for point in result.points:
        print(
            f"{point.files} files: cold={point.cold_duration_ms:.2f}ms, "
            f"warm-p95={point.warm_p95_duration_ms:.2f}ms, "
            f"one-file-refresh={point.single_file_refresh_ms:.2f}ms"
        )
    print(f"报告：{json_path} / {markdown_path}")
    return 0


def _create_synthetic_repository(repository: Path, file_count: int) -> None:
    repository.mkdir(parents=True)
    for index in range(file_count - 1):
        package = repository / f"package_{index % 20:02d}"
        package.mkdir(exist_ok=True)
        (package / f"worker_{index:05d}.py").write_text(
            f"def worker_{index}(payload):\n    return payload\n",
            encoding="utf-8",
        )
    (repository / "critical_payment_handler.py").write_text(
        "def critical_payment_handler(payment):\n    return payment\n",
        encoding="utf-8",
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile)))
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
