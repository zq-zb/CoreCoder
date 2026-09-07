"""离线故障注入 Campaign：验证任务恢复、幂等和审批防重放。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .security import ApprovalManager
from .task_store import TaskStatus, TaskStore


@dataclass(frozen=True)
class FaultScenarioResult:
    name: str
    passed: bool
    expected: str
    actual: str
    recovery_ms: float
    evidence: dict[str, object]


@dataclass(frozen=True)
class ResilienceCampaignReport:
    created_at_utc: str
    total_scenarios: int
    passed_scenarios: int
    pass_rate: float
    total_duration_ms: float
    scenarios: tuple[FaultScenarioResult, ...]


def run_resilience_campaign() -> ResilienceCampaignReport:
    """运行不调用模型和网络的确定性故障演练。"""

    started = time.perf_counter()
    scenarios: tuple[Callable[[], FaultScenarioResult], ...] = (
        _worker_loss_requeues_task,
        _retry_exhaustion_fails_task,
        _cancelled_worker_loss_finishes_cancel,
        _idempotency_storm_creates_one_task,
        _approval_replay_is_rejected,
    )
    results = tuple(scenario() for scenario in scenarios)
    passed = sum(result.passed for result in results)
    return ResilienceCampaignReport(
        created_at_utc=datetime.now(UTC).isoformat(),
        total_scenarios=len(results),
        passed_scenarios=passed,
        pass_rate=passed / len(results),
        total_duration_ms=round((time.perf_counter() - started) * 1000, 3),
        scenarios=results,
    )


def _worker_loss_requeues_task() -> FaultScenarioResult:
    now = [100.0]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="corecoder-fault-worker-") as directory:
        store = TaskStore(Path(directory) / "tasks.db", clock=lambda: now[0])
        task = store.enqueue("coding", {}, max_attempts=3)
        store.claim_next("lost-worker", lease_seconds=5)
        now[0] = 106.0
        recovered = store.recover_expired()
        actual = store.get(task.task_id)
    return _scenario(
        "worker_loss_requeue",
        expected=TaskStatus.PENDING.value,
        actual=actual.status.value,
        started=started,
        evidence={"recovered_tasks": recovered, "attempts": actual.attempts},
    )


def _retry_exhaustion_fails_task() -> FaultScenarioResult:
    now = [200.0]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="corecoder-fault-retry-") as directory:
        store = TaskStore(Path(directory) / "tasks.db", clock=lambda: now[0])
        task = store.enqueue("coding", {}, max_attempts=1)
        store.claim_next("lost-worker", lease_seconds=5)
        now[0] = 206.0
        store.recover_expired()
        actual = store.get(task.task_id)
    return _scenario(
        "retry_exhaustion",
        expected=TaskStatus.FAILED.value,
        actual=actual.status.value,
        started=started,
        evidence={"attempts": actual.attempts, "last_error": actual.last_error or ""},
    )


def _cancelled_worker_loss_finishes_cancel() -> FaultScenarioResult:
    now = [300.0]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="corecoder-fault-cancel-") as directory:
        store = TaskStore(Path(directory) / "tasks.db", clock=lambda: now[0])
        task = store.enqueue("coding", {})
        store.claim_next("lost-worker", lease_seconds=5)
        requested = store.request_cancel(task.task_id)
        now[0] = 306.0
        store.recover_expired()
        actual = store.get(task.task_id)
    return _scenario(
        "cancel_during_worker_loss",
        expected=TaskStatus.CANCELLED.value,
        actual=actual.status.value,
        started=started,
        evidence={"intermediate_status": requested.status.value},
    )


def _idempotency_storm_creates_one_task() -> FaultScenarioResult:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="corecoder-fault-idempotency-") as directory:
        store = TaskStore(Path(directory) / "tasks.db")

        def submit(_):
            return store.enqueue("coding", {"task": "same"}, idempotency_key="incident-001").task_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            task_ids = list(pool.map(submit, range(64)))
        unique = len(set(task_ids))
        stored = len(store.list_tasks())
    return _scenario(
        "idempotency_storm",
        expected="1",
        actual=str(unique),
        started=started,
        evidence={"submissions": 64, "unique_task_ids": unique, "stored_tasks": stored},
    )


def _approval_replay_is_rejected() -> FaultScenarioResult:
    started = time.perf_counter()
    approvals = ApprovalManager(ttl_seconds=60)
    request = approvals.request("git push origin main", "改变远端")
    approvals.approve(request.request_id, "fault-reviewer")
    first = approvals.consume("git push origin main")
    second = approvals.consume("git push origin main")
    actual = "rejected" if first and second is None else "allowed"
    return _scenario(
        "approval_replay",
        expected="rejected",
        actual=actual,
        started=started,
        evidence={
            "first_status": first.status.value if first else "missing",
            "second_allowed": second is not None,
            "final_status": approvals.get(request.request_id).status.value,
        },
    )

def _scenario(
    name: str,
    *,
    expected: str,
    actual: str,
    started: float,
    evidence: dict[str, object],
) -> FaultScenarioResult:
    return FaultScenarioResult(
        name=name,
        passed=expected == actual,
        expected=expected,
        actual=actual,
        recovery_ms=round((time.perf_counter() - started) * 1000, 3),
        evidence=evidence,
    )


def write_resilience_report(report: ResilienceCampaignReport, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "resilience-campaign.json"
    markdown_path = destination / "resilience-campaign.md"
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CoreCoder Resilience Campaign",
        "",
        f"- Scenarios: {report.passed_scenarios}/{report.total_scenarios}",
        f"- Pass rate: {report.pass_rate:.1%}",
        f"- Total duration: {report.total_duration_ms:.3f} ms",
        "",
        "| Scenario | Expected | Actual | Recovery | Result |",
        "|---|---|---|---:|---:|",
    ]
    for result in report.scenarios:
        lines.append(
            f"| {result.name} | {result.expected} | {result.actual} | "
            f"{result.recovery_ms:.3f} ms | {'PASS' if result.passed else 'FAIL'} |"
        )
    lines.extend(["", "## Evidence", ""])
    for result in report.scenarios:
        lines.extend([
            f"### {result.name}",
            "",
            "```json",
            json.dumps(result.evidence, ensure_ascii=False, indent=2),
            "```",
            "",
        ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="运行 CoreCoder 离线故障演练")
    parser.add_argument("--output", type=Path, default=Path("evals/reports/resilience"))
    options = parser.parse_args(argv)
    report = run_resilience_campaign()
    json_path, markdown_path = write_resilience_report(report, options.output)
    print(f"故障演练：{report.passed_scenarios}/{report.total_scenarios} ({report.pass_rate:.1%})")
    for result in report.scenarios:
        print(f"- {result.name}: {'PASS' if result.passed else 'FAIL'} ({result.recovery_ms:.3f} ms)")
    print(f"报告：{markdown_path.resolve()}（JSON: {json_path.resolve()}）")
    return 0 if report.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
