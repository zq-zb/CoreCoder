"""从持久化任务台账导出低基数运行指标。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .task_store import TaskRecord, TaskStatus, TaskStore


@dataclass(frozen=True)
class TaskMetricsSnapshot:
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    succeeded_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    cancel_requested_tasks: int
    terminal_success_ratio: float
    retry_tasks: int
    total_attempts: int
    expired_leases: int
    oldest_pending_age_seconds: float


def collect_task_metrics(store: TaskStore, *, now: float | None = None) -> TaskMetricsSnapshot:
    """读取一个一致用途的指标快照；只输出固定字段，避免标签基数爆炸。"""

    now = time.time() if now is None else now
    tasks = store.list_tasks()
    counts = {status: 0 for status in TaskStatus}
    for task in tasks:
        counts[task.status] += 1
    terminal = counts[TaskStatus.SUCCEEDED] + counts[TaskStatus.FAILED]
    pending_ages = [max(0.0, now - task.created_at) for task in tasks if task.status is TaskStatus.PENDING]
    return TaskMetricsSnapshot(
        total_tasks=len(tasks),
        pending_tasks=counts[TaskStatus.PENDING],
        running_tasks=counts[TaskStatus.RUNNING],
        succeeded_tasks=counts[TaskStatus.SUCCEEDED],
        failed_tasks=counts[TaskStatus.FAILED],
        cancelled_tasks=counts[TaskStatus.CANCELLED],
        cancel_requested_tasks=counts[TaskStatus.CANCEL_REQUESTED],
        terminal_success_ratio=round(counts[TaskStatus.SUCCEEDED] / terminal, 6) if terminal else 0.0,
        retry_tasks=sum(task.attempts > 1 for task in tasks),
        total_attempts=sum(task.attempts for task in tasks),
        expired_leases=sum(_lease_expired(task, now) for task in tasks),
        oldest_pending_age_seconds=round(max(pending_ages, default=0.0), 3),
    )


def render_prometheus(snapshot: TaskMetricsSnapshot) -> str:
    """输出可被 Prometheus textfile collector 或监控采集器读取的文本。"""

    status_values = {
        "pending": snapshot.pending_tasks,
        "running": snapshot.running_tasks,
        "succeeded": snapshot.succeeded_tasks,
        "failed": snapshot.failed_tasks,
        "cancelled": snapshot.cancelled_tasks,
        "cancel_requested": snapshot.cancel_requested_tasks,
    }
    lines = [
        "# HELP corecoder_tasks Current tasks by status.",
        "# TYPE corecoder_tasks gauge",
        *(f'corecoder_tasks{{status="{status}"}} {value}' for status, value in status_values.items()),
        "# HELP corecoder_task_terminal_success_ratio Ratio of succeeded terminal tasks.",
        "# TYPE corecoder_task_terminal_success_ratio gauge",
        f"corecoder_task_terminal_success_ratio {snapshot.terminal_success_ratio}",
        "# HELP corecoder_task_attempts Total task execution attempts.",
        "# TYPE corecoder_task_attempts counter",
        f"corecoder_task_attempts {snapshot.total_attempts}",
        "# HELP corecoder_task_retries Tasks attempted more than once.",
        "# TYPE corecoder_task_retries gauge",
        f"corecoder_task_retries {snapshot.retry_tasks}",
        "# HELP corecoder_task_expired_leases Running tasks whose lease has expired.",
        "# TYPE corecoder_task_expired_leases gauge",
        f"corecoder_task_expired_leases {snapshot.expired_leases}",
        "# HELP corecoder_task_oldest_pending_age_seconds Age of the oldest pending task.",
        "# TYPE corecoder_task_oldest_pending_age_seconds gauge",
        f"corecoder_task_oldest_pending_age_seconds {snapshot.oldest_pending_age_seconds}",
    ]
    return "\n".join(lines) + "\n"


def _lease_expired(task: TaskRecord, now: float) -> bool:
    return (
        task.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}
        and task.lease_expires_at is not None
        and task.lease_expires_at <= now
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="导出 CoreCoder 任务运行指标")
    parser.add_argument("--store", type=Path, default=Path(".corecoder/tasks.db"))
    parser.add_argument("--format", choices=("prometheus", "json"), default="prometheus")
    options = parser.parse_args(argv)
    snapshot = collect_task_metrics(TaskStore(options.store))
    if options.format == "json":
        print(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2))
    else:
        print(render_prometheus(snapshot), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
