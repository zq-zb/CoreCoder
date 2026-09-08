"""持久化任务台账、租约、重试、取消和并发领取测试。"""

import concurrent.futures
import os
import sqlite3

from corecoder.task_store import TaskStatus, TaskStore


def test_task_lifecycle_is_persisted_across_store_instances(tmp_path):
    path = tmp_path / "tasks.db"
    first = TaskStore(path)
    pending = first.enqueue("coding", {"task": "修复计算器"})
    running = first.claim_next("worker-a", lease_seconds=30)

    assert running.task_id == pending.task_id
    assert running.status is TaskStatus.RUNNING
    assert running.attempts == 1

    second = TaskStore(path)
    completed = second.finish(running.task_id, "worker-a", succeeded=True, result={"tests": "passed"})

    assert completed.status is TaskStatus.SUCCEEDED
    assert completed.result == {"tests": "passed"}
    assert completed.worker_id is None


def test_concurrent_workers_claim_one_task_only_once(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {"task": "one"})

    def claim(index):
        return store.claim_next(f"worker-{index}", lease_seconds=30)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))

    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    assert claimed[0].task_id == task.task_id


def test_expired_lease_requeues_then_fails_at_attempt_limit(tmp_path):
    now = [100.0]
    store = TaskStore(tmp_path / "tasks.db", clock=lambda: now[0])
    task = store.enqueue("coding", {}, max_attempts=2)
    store.claim_next("worker-a", lease_seconds=10)
    now[0] = 111.0

    assert store.recover_expired() == 1
    assert store.get(task.task_id).status is TaskStatus.PENDING

    second = store.claim_next("worker-b", lease_seconds=10)
    assert second.attempts == 2
    now[0] = 122.0
    assert store.recover_expired() == 1

    failed = store.get(task.task_id)
    assert failed.status is TaskStatus.FAILED
    assert "最大尝试次数" in failed.last_error


def test_heartbeat_requires_lease_owner_and_extends_lease(tmp_path):
    now = [50.0]
    store = TaskStore(tmp_path / "tasks.db", clock=lambda: now[0])
    task = store.enqueue("coding", {})
    store.claim_next("worker-a", lease_seconds=10)
    now[0] = 55.0

    renewed = store.heartbeat(task.task_id, "worker-a", lease_seconds=20)

    assert renewed.lease_expires_at == 75.0
    try:
        store.heartbeat(task.task_id, "worker-b")
    except ValueError as error:
        assert "不属于该 Worker" in str(error)
    else:
        raise AssertionError("其他 Worker 不能续租")


def test_running_task_uses_two_phase_cancellation(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {})
    store.claim_next("worker-a")

    requested = store.request_cancel(task.task_id)
    assert requested.status is TaskStatus.CANCEL_REQUESTED

    cancelled = store.acknowledge_cancel(task.task_id, "worker-a")
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.worker_id is None


def test_pending_task_cancels_immediately_and_cannot_be_claimed(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {})

    cancelled = store.request_cancel(task.task_id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert store.claim_next("worker-a") is None


def test_wrong_worker_cannot_finish_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {})
    store.claim_next("worker-a")

    try:
        store.finish(task.task_id, "worker-b", succeeded=True)
    except ValueError as error:
        assert "持有 RUNNING 租约" in str(error)
    else:
        raise AssertionError("非租约持有者不能结束任务")


def test_database_connections_release_windows_file_handle(tmp_path):
    database = tmp_path / "tasks.db"
    moved = tmp_path / "moved.db"
    store = TaskStore(database)
    task = store.enqueue("coding", {})
    store.get(task.task_id)
    store.list_tasks()

    os.replace(database, moved)

    assert moved.exists()


def test_idempotency_key_returns_same_task_for_retried_submission(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    first = store.enqueue("coding", {"task": "same"}, idempotency_key="request-001")
    second = store.enqueue("coding", {"task": "same"}, idempotency_key="request-001")

    assert second.task_id == first.task_id
    assert len(store.list_tasks()) == 1


def test_concurrent_idempotent_enqueues_create_one_task(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")

    def enqueue(_):
        return store.enqueue("coding", {"task": "same"}, idempotency_key="concurrent-001")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(enqueue, range(8)))

    assert len({result.task_id for result in results}) == 1
    assert len(store.list_tasks()) == 1


def test_reusing_idempotency_key_for_different_payload_is_rejected(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    store.enqueue("coding", {"task": "first"}, idempotency_key="request-002")

    try:
        store.enqueue("coding", {"task": "different"}, idempotency_key="request-002")
    except ValueError as error:
        assert "不同的任务内容" in str(error)
    else:
        raise AssertionError("同一幂等键不能代表不同任务")


def test_higher_priority_task_is_claimed_first(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    low = store.enqueue("coding", {"task": "low"}, priority=0)
    high = store.enqueue("coding", {"task": "high"}, priority=50)

    claimed = store.claim_next("worker-a")

    assert claimed.task_id == high.task_id
    assert store.get(low.task_id).status is TaskStatus.PENDING


def test_legacy_database_is_migrated_without_losing_tasks(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, payload_json TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
            worker_id TEXT, lease_expires_at REAL, result_json TEXT, last_error TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, version INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO tasks VALUES (
            'legacy-1', 'coding', '{}', 'pending', 0, 3, NULL, NULL, NULL, NULL, 1, 1, 0
        )
        """
    )
    connection.commit()
    connection.close()

    store = TaskStore(database)
    legacy = store.get("legacy-1")
    new = store.enqueue("coding", {"task": "new"}, idempotency_key="new-key", priority=10)

    assert legacy.priority == 0
    assert legacy.idempotency_key is None
    assert new.priority == 10
    with sqlite3.connect(database) as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 2
