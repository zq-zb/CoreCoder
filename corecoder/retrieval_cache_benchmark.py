"""测量仓库检索冷启动与缓存命中的延迟。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .tools.repository_search import RepositorySearchTool


@dataclass(frozen=True)
class RetrievalCacheBenchmark:
    repository: str
    query: str
    repetitions: int
    cold_duration_ms: float
    warm_durations_ms: tuple[float, ...]
    average_warm_duration_ms: float
    speedup: float
    cache_hits: int
    index_builds: int


def run_cache_benchmark(
    repository: str | Path,
    query: str,
    *,
    repetitions: int = 5,
) -> RetrievalCacheBenchmark:
    """在同一工具实例内执行一次冷查询和多次热查询。"""

    if repetitions < 2:
        raise ValueError("repetitions 必须至少为 2")
    tool = RepositorySearchTool()
    durations: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        tool.execute(query, str(repository), limit=5)
        durations.append((time.perf_counter() - started) * 1000)
    warm_average = statistics.mean(durations[1:])
    stats = tool.stats()
    return RetrievalCacheBenchmark(
        # 报告保留调用方给出的可复现路径，避免泄漏开发机用户名等绝对路径。
        repository=str(repository),
        query=query,
        repetitions=repetitions,
        cold_duration_ms=durations[0],
        warm_durations_ms=tuple(durations[1:]),
        average_warm_duration_ms=warm_average,
        speedup=durations[0] / warm_average if warm_average else 0.0,
        cache_hits=stats.cache_hits,
        index_builds=stats.index_builds,
    )


def write_cache_benchmark_report(result: RetrievalCacheBenchmark, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "retrieval-cache-benchmark.json"
    markdown_path = destination / "retrieval-cache-benchmark.md"
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(
        "\n".join(
            [
                "# CoreCoder Retrieval Cache Benchmark",
                "",
                f"- Repository: `{result.repository}`",
                f"- Query: `{result.query}`",
                f"- Repetitions: {result.repetitions}",
                f"- Cold query: {result.cold_duration_ms:.2f} ms",
                f"- Average warm query: {result.average_warm_duration_ms:.2f} ms",
                f"- Cold/warm speedup: {result.speedup:.2f}x",
                f"- Cache hits / index builds: {result.cache_hits} / {result.index_builds}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Benchmark repository retrieval cache")
    parser.add_argument("--repository", default=".")
    parser.add_argument("--query", default="MCP runtime circuit breaker repository search")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="evals/reports/retrieval-cache")
    args = parser.parse_args(argv)
    result = run_cache_benchmark(args.repository, args.query, repetitions=args.repetitions)
    json_path, markdown_path = write_cache_benchmark_report(result, args.output)
    print(f"冷查询：{result.cold_duration_ms:.2f} ms")
    print(f"热查询均值：{result.average_warm_duration_ms:.2f} ms")
    print(f"加速比：{result.speedup:.2f}x")
    print(f"报告：{json_path} / {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
