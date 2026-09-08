"""单机持久化任务台账：原子领取、租约、重试和取消状态机。"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    task_type: str
    idempotency_key: str | None
    priority: int
    payload: dict[str, Any]
    status: TaskStatus
    attempts: int
    max_attempts: int
    worker_id: str | None
    lease_expires_at: float | None
    result: dict[str, Any] | None
    last_error: str | None
    created_at: float
    updated_at: float
    version: int


class TaskStore:
    """SQLite 任务存储；每次操作使用独立连接，支持多线程 Worker。"""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._initialize()

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        priority: int = 0,
    ) -> TaskRecord:
        """提交任务；兼容原有调用方，只返回任务记录。"""

        record, _ = self.enqueue_with_created(
            task_type,
            payload,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            priority=priority,
        )
        return record

    def enqueue_with_created(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        priority: int = 0,
    ) -> tuple[TaskRecord, bool]:
        """提交任务并原子返回是否新建，避免调用方先查后写的竞态。"""

        if not task_type.strip():
            raise ValueError("任务类型不能为空")
        if max_attempts <= 0:
            raise ValueError("最大尝试次数必须大于 0")
        if not -100 <= priority <= 100:
            raise ValueError("任务优先级必须在 -100 到 100 之间")
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if idempotency_key is not None and not normalized_key:
            raise ValueError("幂等键不能为空字符串")
        now = self._clock()
        task_id = uuid.uuid4().hex
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, task_type, idempotency_key, priority, payload_json, status,
                        attempts, max_attempts, created_at, updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0)
                    """,
                    (task_id, task_type.strip(), normalized_key, priority, payload_json,
                     TaskStatus.PENDING.value, max_attempts, now, now),
                )
        except sqlite3.IntegrityError:
            if normalized_key is None:
                raise
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE idempotency_key = ?", (normalized_key,)
                ).fetchone()
            if row is None:
                raise
            existing = _to_record(row)
            if existing.task_type != task_type.strip() or existing.payload != payload:
                raise ValueError("幂等键已用于不同的任务内容") from None
            return existing, False
        return self.get(task_id), True

    def claim_next(self, worker_id: str, *, lease_seconds: float = 60) -> TaskRecord | None:
        if not worker_id.strip() or lease_seconds <= 0:
            raise ValueError("Worker ID 不能为空，租约时间必须大于 0")
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._recover_expired_locked(connection, now)
            row = connection.execute(
                """
                SELECT task_id, version FROM tasks WHERE status = ?
                ORDER BY priority DESC, created_at, task_id LIMIT 1
                """,
                (TaskStatus.PENDING.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE tasks SET status = ?, worker_id = ?, lease_expires_at = ?, attempts = attempts + 1,
                    updated_at = ?, version = version + 1
                WHERE task_id = ? AND version = ? AND status = ?
                """,
                (TaskStatus.RUNNING.value, worker_id.strip(), now + lease_seconds, now,
                 row["task_id"], row["version"], TaskStatus.PENDING.value),
            )
            connection.commit()
        return self.get(row["task_id"])

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: float = 60) -> TaskRecord:
        if lease_seconds <= 0:
            raise ValueError("租约时间必须大于 0")
        now = self._clock()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET lease_expires_at = ?, updated_at = ?, version = version + 1
                WHERE task_id = ? AND worker_id = ? AND status IN (?, ?)
                """,
                (now + lease_seconds, now, task_id, worker_id,
                 TaskStatus.RUNNING.value, TaskStatus.CANCEL_REQUESTED.value),
            )
            if cursor.rowcount != 1:
                raise ValueError("任务不存在、租约不属于该 Worker，或任务已结束")
        return self.get(task_id)

    def finish(
        self,
        task_id: str,
        worker_id: str,
        *,
        succeeded: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        status = TaskStatus.SUCCEEDED if succeeded else TaskStatus.FAILED
        now = self._clock()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET status = ?, result_json = ?, last_error = ?, worker_id = NULL,
                    lease_expires_at = NULL, updated_at = ?, version = version + 1
                WHERE task_id = ? AND worker_id = ? AND status = ?
                """,
                (status.value, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, now, task_id, worker_id, TaskStatus.RUNNING.value),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有持有 RUNNING 租约的 Worker 可以结束任务")
        return self.get(task_id)

    def request_cancel(self, task_id: str) -> TaskRecord:
        now = self._clock()
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"任务不存在：{task_id}")
            current = TaskStatus(row["status"])
            if current is TaskStatus.PENDING:
                target = TaskStatus.CANCELLED
            elif current is TaskStatus.RUNNING:
                target = TaskStatus.CANCEL_REQUESTED
            else:
                raise ValueError(f"当前状态不能取消：{current.value}")
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, version = version + 1 WHERE task_id = ?",
                (target.value, now, task_id),
            )
        return self.get(task_id)

    def acknowledge_cancel(self, task_id: str, worker_id: str) -> TaskRecord:
        now = self._clock()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET status = ?, worker_id = NULL, lease_expires_at = NULL,
                    updated_at = ?, version = version + 1
                WHERE task_id = ? AND worker_id = ? AND status = ?
                """,
                (TaskStatus.CANCELLED.value, now, task_id, worker_id, TaskStatus.CANCEL_REQUESTED.value),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有持有租约的 Worker 可以确认取消")
        return self.get(task_id)

    def recover_expired(self) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = self._recover_expired_locked(connection, self._clock())
            connection.commit()
            return changed

    def get(self, task_id: str) -> TaskRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"任务不存在：{task_id}")
        return _to_record(row)

    def list_tasks(self, *, status: TaskStatus | None = None) -> tuple[TaskRecord, ...]:
        with self._connect() as connection:
            if status is None:
                rows = connection.execute("SELECT * FROM tasks ORDER BY created_at, task_id").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at, task_id",
                    (status.value,),
                ).fetchall()
        return tuple(_to_record(row) for row in rows)

    def _recover_expired_locked(self, connection: sqlite3.Connection, now: float) -> int:
        # 已收到取消请求的任务在 Worker 失联后直接取消；普通运行任务则重试或失败。
        cancelled = connection.execute(
            """
            UPDATE tasks SET status = ?, worker_id = NULL, lease_expires_at = NULL,
                updated_at = ?, version = version + 1
            WHERE status = ? AND lease_expires_at <= ?
            """,
            (TaskStatus.CANCELLED.value, now, TaskStatus.CANCEL_REQUESTED.value, now),
        ).rowcount
        failed = connection.execute(
            """
            UPDATE tasks SET status = ?, worker_id = NULL, lease_expires_at = NULL,
                last_error = ?, updated_at = ?, version = version + 1
            WHERE status = ? AND lease_expires_at <= ? AND attempts >= max_attempts
            """,
            (TaskStatus.FAILED.value, "Worker 租约过期且达到最大尝试次数", now,
             TaskStatus.RUNNING.value, now),
        ).rowcount
        retried = connection.execute(
            """
            UPDATE tasks SET status = ?, worker_id = NULL, lease_expires_at = NULL,
                last_error = ?, updated_at = ?, version = version + 1
            WHERE status = ? AND lease_expires_at <= ? AND attempts < max_attempts
            """,
            (TaskStatus.PENDING.value, "Worker 租约过期，任务已重新入队", now,
             TaskStatus.RUNNING.value, now),
        ).rowcount
        return cancelled + failed + retried

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 10000")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    idempotency_key TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    worker_id TEXT,
                    lease_expires_at REAL,
                    result_json TEXT,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    version INTEGER NOT NULL
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "idempotency_key" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN idempotency_key TEXT")
            if "priority" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(status, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(status, lease_expires_at)")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )
            connection.execute("PRAGMA user_version = 2")


def _to_record(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=row["task_id"],
        task_type=row["task_type"],
        idempotency_key=row["idempotency_key"],
        priority=row["priority"],
        payload=json.loads(row["payload_json"]),
        status=TaskStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        worker_id=row["worker_id"],
        lease_expires_at=row["lease_expires_at"],
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )
