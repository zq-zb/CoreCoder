"""持久化任务台账的本地运维入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .task_store import TaskStatus, TaskStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 CoreCoder 持久化任务")
    parser.add_argument("--store", type=Path, default=Path(".corecoder/tasks.db"))
    commands = parser.add_subparsers(dest="action", required=True)

    enqueue = commands.add_parser("enqueue", help="提交 Coding 任务")
    enqueue.add_argument("--task", required=True)
    enqueue.add_argument("--workspace", type=Path, required=True)
    enqueue.add_argument("--max-attempts", type=int, default=3)
    enqueue.add_argument("--idempotency-key")
    enqueue.add_argument("--priority", type=int, default=0)

    listing = commands.add_parser("list", help="列出任务")
    listing.add_argument("--status", choices=tuple(status.value for status in TaskStatus))

    cancel = commands.add_parser("cancel", help="请求取消任务")
    cancel.add_argument("task_id")

    commands.add_parser("recover", help="回收租约已过期的任务")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    options = _parser().parse_args(argv)
    store = TaskStore(options.store)
    try:
        if options.action == "enqueue":
            workspace = options.workspace.expanduser().resolve()
            if not workspace.is_dir():
                print(f"任务提交失败：工作区不存在：{workspace}")
                return 2
            task = store.enqueue(
                "coding",
                {"task": options.task, "workspace": str(workspace)},
                max_attempts=options.max_attempts,
                idempotency_key=options.idempotency_key,
                priority=options.priority,
            )
            print(f"任务已提交：{task.task_id}")
            return 0
        if options.action == "cancel":
            task = store.request_cancel(options.task_id)
            print(f"取消状态：{task.task_id} -> {task.status.value}")
            return 0
        if options.action == "recover":
            print(f"已回收 {store.recover_expired()} 个过期租约任务")
            return 0

        status = TaskStatus(options.status) if options.status else None
        tasks = store.list_tasks(status=status)
        if not tasks:
            print("当前没有任务。")
            return 0
        for task in tasks:
            worker = task.worker_id or "-"
            print(
                f"{task.task_id}  {task.status.value:16} "
                f"priority={task.priority} attempts={task.attempts}/{task.max_attempts} "
                f"worker={worker} type={task.task_type}"
            )
        return 0
    except (KeyError, ValueError) as error:
        print(f"任务操作失败：{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
