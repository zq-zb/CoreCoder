"""比较两份 Agent 评测报告，并主动识别无效或证据不足的实验。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationComparison:
    baseline_strategy: str
    candidate_strategy: str
    comparable: bool
    cases_per_group: int
    success_rate_delta: float
    hidden_test_pass_rate_delta: float
    average_tool_calls_delta: float
    average_duration_seconds_delta: float
    average_prompt_tokens_delta: float
    average_completion_tokens_delta: float
    candidate_repository_search_calls: int
    candidate_retrieval_policy_rejections: int
    warnings: tuple[str, ...]


def compare_evaluation_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> EvaluationComparison:
    baseline_metadata = baseline.get("metadata") or {}
    candidate_metadata = candidate.get("metadata") or {}
    comparable_fields = ("model", "provider", "dataset_fingerprint")
    mismatches = [
        field for field in comparable_fields if baseline_metadata.get(field) != candidate_metadata.get(field)
    ]
    baseline_results = baseline.get("results") or []
    candidate_results = candidate.get("results") or []
    warnings: list[str] = []
    if mismatches:
        warnings.append(f"实验元数据不一致：{', '.join(mismatches)}")
    if len(baseline_results) != len(candidate_results):
        warnings.append("两组运行数量不一致")
    cases_per_group = min(len(baseline_results), len(candidate_results))
    if cases_per_group < 3:
        warnings.append("每组少于 3 次结果，只能视为链路冒烟，不能证明稳定提升")

    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    repository_calls = int(candidate_summary.get("total_repository_search_calls", 0))
    candidate_strategy = str(candidate_metadata.get("strategy", ""))
    retrieval_enabled = "retrieval-" in candidate_strategy and "retrieval-off" not in candidate_strategy
    if retrieval_enabled and repository_calls == 0:
        warnings.append("候选组没有实际调用 repository_search，不能归因于检索能力")
    if baseline_summary.get("total_estimated_cost") is None or candidate_summary.get("total_estimated_cost") is None:
        warnings.append("模型费用不可用，应使用 Token 指标比较资源消耗")
    policy_rejections = candidate_summary.get("total_retrieval_policy_rejections")
    if policy_rejections is None and "retrieval-guided" in candidate_strategy:
        policy_rejections = _infer_guided_rejections(candidate_results)

    return EvaluationComparison(
        baseline_strategy=str(baseline_metadata.get("strategy", "unknown")),
        candidate_strategy=str(candidate_metadata.get("strategy", "unknown")),
        comparable=not mismatches and len(baseline_results) == len(candidate_results),
        cases_per_group=cases_per_group,
        success_rate_delta=_delta(candidate_summary, baseline_summary, "success_rate"),
        hidden_test_pass_rate_delta=_delta(candidate_summary, baseline_summary, "hidden_test_pass_rate"),
        average_tool_calls_delta=_delta(candidate_summary, baseline_summary, "average_tool_calls"),
        average_duration_seconds_delta=_delta(candidate_summary, baseline_summary, "average_duration_seconds"),
        average_prompt_tokens_delta=_average_delta(candidate_summary, baseline_summary, "total_prompt_tokens"),
        average_completion_tokens_delta=_average_delta(candidate_summary, baseline_summary, "total_completion_tokens"),
        candidate_repository_search_calls=repository_calls,
        candidate_retrieval_policy_rejections=int(policy_rejections or 0),
        warnings=tuple(warnings),
    )


def write_comparison_report(result: EvaluationComparison, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "evaluation-comparison.json"
    markdown_path = destination / "evaluation-comparison.md"
    json_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CoreCoder Evaluation Comparison",
        "",
        f"- Baseline: `{result.baseline_strategy}`",
        f"- Candidate: `{result.candidate_strategy}`",
        f"- Comparable metadata: {'yes' if result.comparable else 'no'}",
        f"- Results per group: {result.cases_per_group}",
        f"- Candidate repository searches: {result.candidate_repository_search_calls}",
        f"- Candidate policy rejections: {result.candidate_retrieval_policy_rejections}",
        "",
        "| Metric | Candidate - baseline |",
        "|---|---:|",
        f"| Success rate | {result.success_rate_delta:+.1%} |",
        f"| Hidden test pass rate | {result.hidden_test_pass_rate_delta:+.1%} |",
        f"| Average tool calls | {result.average_tool_calls_delta:+.2f} |",
        f"| Average duration | {result.average_duration_seconds_delta:+.2f}s |",
        f"| Average prompt tokens | {result.average_prompt_tokens_delta:+.0f} |",
        f"| Average completion tokens | {result.average_completion_tokens_delta:+.0f} |",
        "",
        "## Evidence warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("- None")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare two CoreCoder evaluation reports")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/comparison"))
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = compare_evaluation_reports(baseline, candidate)
    json_path, markdown_path = write_comparison_report(result, args.output)
    print(f"元数据可比：{'是' if result.comparable else '否'}")
    print(f"证据警告：{len(result.warnings)}")
    print(f"报告：{json_path} / {markdown_path}")
    return 0 if result.comparable else 1


def _delta(candidate: dict[str, Any], baseline: dict[str, Any], field: str) -> float:
    return float(candidate.get(field, 0.0)) - float(baseline.get(field, 0.0))


def _average_delta(candidate: dict[str, Any], baseline: dict[str, Any], field: str) -> float:
    candidate_cases = max(1, int(candidate.get("total_cases", 0)))
    baseline_cases = max(1, int(baseline.get("total_cases", 0)))
    return float(candidate.get(field, 0)) / candidate_cases - float(baseline.get(field, 0)) / baseline_cases


def _infer_guided_rejections(results: list[dict[str, Any]]) -> int:
    """兼容指标字段加入前的 guided 报告，从首次检索前的轨迹恢复拒绝数。"""

    guarded = {"bash", "glob", "grep", "read_file", "edit_file", "write_file"}
    total = 0
    for result in results:
        for tool_name in result.get("tool_trace", []):
            if tool_name == "repository_search":
                break
            if tool_name in guarded:
                total += 1
    return total


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
