"""离线评测仓库检索质量，不调用 LLM 或外部服务。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .evaluation import EvaluationCase, discover_cases
from .repository import RepositoryIndex


@dataclass(frozen=True)
class RetrievalBenchmarkCase:
    case_id: str
    indexed_files: int
    relevant_files: tuple[str, ...]
    ranked_files: tuple[str, ...]
    target_recall_at_1: float
    target_recall_at_3: float
    target_recall_at_5: float
    context_recall_at_1: float
    context_recall_at_3: float
    context_recall_at_5: float
    first_relevant_rank: int | None
    duration_seconds: float


@dataclass(frozen=True)
class RetrievalBenchmarkSummary:
    cases: int
    average_target_recall_at_1: float
    average_target_recall_at_3: float
    average_target_recall_at_5: float
    average_context_recall_at_1: float
    average_context_recall_at_3: float
    average_context_recall_at_5: float
    mean_reciprocal_rank: float
    average_duration_seconds: float


def run_retrieval_benchmark(
    cases: list[EvaluationCase],
    *,
    max_results: int = 5,
) -> tuple[list[RetrievalBenchmarkCase], RetrievalBenchmarkSummary]:
    """使用案例任务文本查询其仓库，并与人工上下文真值对照。"""

    benchmark_cases = [case for case in cases if case.relevant_context_files]
    results: list[RetrievalBenchmarkCase] = []
    for case in benchmark_cases:
        started = time.perf_counter()
        index = RepositoryIndex.build(case.workspace_dir)
        hits = index.search(case.task, limit=max(5, max_results))
        ranked = tuple(hit.path for hit in hits)
        targets = set(case.allowed_changed_files)
        contexts = set(case.relevant_context_files)
        relevant_ranks = [position for position, path in enumerate(ranked, 1) if path in contexts]
        results.append(
            RetrievalBenchmarkCase(
                case_id=case.case_id,
                indexed_files=len(index.documents),
                relevant_files=case.relevant_context_files,
                ranked_files=ranked[:max_results],
                target_recall_at_1=_recall(ranked[:1], targets),
                target_recall_at_3=_recall(ranked[:3], targets),
                target_recall_at_5=_recall(ranked[:5], targets),
                context_recall_at_1=_recall(ranked[:1], contexts),
                context_recall_at_3=_recall(ranked[:3], contexts),
                context_recall_at_5=_recall(ranked[:5], contexts),
                first_relevant_rank=min(relevant_ranks) if relevant_ranks else None,
                duration_seconds=time.perf_counter() - started,
            )
        )
    return results, summarize_retrieval_benchmark(results)


def summarize_retrieval_benchmark(
    results: list[RetrievalBenchmarkCase],
) -> RetrievalBenchmarkSummary:
    if not results:
        return RetrievalBenchmarkSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    total = len(results)
    return RetrievalBenchmarkSummary(
        cases=total,
        average_target_recall_at_1=sum(item.target_recall_at_1 for item in results) / total,
        average_target_recall_at_3=sum(item.target_recall_at_3 for item in results) / total,
        average_target_recall_at_5=sum(item.target_recall_at_5 for item in results) / total,
        average_context_recall_at_1=sum(item.context_recall_at_1 for item in results) / total,
        average_context_recall_at_3=sum(item.context_recall_at_3 for item in results) / total,
        average_context_recall_at_5=sum(item.context_recall_at_5 for item in results) / total,
        mean_reciprocal_rank=sum(
            0.0 if item.first_relevant_rank is None else 1 / item.first_relevant_rank for item in results
        ) / total,
        average_duration_seconds=sum(item.duration_seconds for item in results) / total,
    )


def write_retrieval_benchmark_report(
    results: list[RetrievalBenchmarkCase],
    summary: RetrievalBenchmarkSummary,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "retrieval-benchmark.json"
    markdown_path = destination / "retrieval-benchmark.md"
    json_path.write_text(
        json.dumps(
            {"summary": asdict(summary), "results": [asdict(result) for result in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    target_recall_line = (
        f"- Target recall @1/@3/@5: {summary.average_target_recall_at_1:.1%} / "
        f"{summary.average_target_recall_at_3:.1%} / {summary.average_target_recall_at_5:.1%}"
    )
    context_recall_line = (
        f"- Context recall @1/@3/@5: {summary.average_context_recall_at_1:.1%} / "
        f"{summary.average_context_recall_at_3:.1%} / {summary.average_context_recall_at_5:.1%}"
    )
    lines = [
        "# CoreCoder Retrieval Benchmark",
        "",
        f"- Cases: {summary.cases}",
        target_recall_line,
        context_recall_line,
        f"- Mean reciprocal rank: {summary.mean_reciprocal_rank:.3f}",
        f"- Average duration: {summary.average_duration_seconds:.6f}s",
        "",
        "| Case | Ranked files | Target R@1/R@3/R@5 | Context R@1/R@3/R@5 | First relevant |",
        "|---|---|---|---|---:|",
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {', '.join(result.ranked_files)} | "
            f"{result.target_recall_at_1:.0%}/{result.target_recall_at_3:.0%}/"
            f"{result.target_recall_at_5:.0%} | "
            f"{result.context_recall_at_1:.0%}/{result.context_recall_at_3:.0%}/"
            f"{result.context_recall_at_5:.0%} | {result.first_relevant_rank or '-'} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the offline repository retrieval benchmark")
    parser.add_argument("--cases", default="evals/cases", help="Evaluation cases directory")
    parser.add_argument("--output", default="evals/reports/retrieval", help="Report output directory")
    args = parser.parse_args(argv)
    results, summary = run_retrieval_benchmark(discover_cases(args.cases))
    json_path, markdown_path = write_retrieval_benchmark_report(results, summary, args.output)
    print(f"检索评测案例：{summary.cases}")
    print(f"Context Recall@3：{summary.average_context_recall_at_3:.1%}")
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")
    return 0 if summary.cases else 1


def _recall(ranked: tuple[str, ...], relevant: set[str]) -> float:
    return len(set(ranked).intersection(relevant)) / len(relevant) if relevant else 0.0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
