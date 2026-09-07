"""任务运行指标测试。"""

import json

from corecoder.metrics import collect_task_metrics, main, render_prometheus
from corecoder.task_store import TaskStore


def test_task_metrics_cover_backlog_success_retry_and_expired_lease(tmp_path):
    now = [90.0]
    store = TaskStore(tmp_path / "tasks.db", clock=lambda: now[0])
    succeeded = store.enqueue("coding", {"name": "success"})
    store.claim_next("worker-a", lease_seconds=5)
    store.finish(succeeded.task_id, "worker-a", succeeded=True)
    now[0] = 91.0
    expired = store.enqueue("coding", {"name": "expired"})
    store.claim_next("worker-b", lease_seconds=5)
    now[0] = 92.0
    store.enqueue("coding", {"name": "pending"})
    now[0] = 100.0

    snapshot = collect_task_metrics(store, now=now[0])

    assert snapshot.total_tasks == 3
    assert snapshot.pending_tasks == 1
    assert snapshot.succeeded_tasks == 1
    assert snapshot.running_tasks == 1
    assert snapshot.terminal_success_ratio == 1.0
    assert snapshot.total_attempts == 2
    assert snapshot.expired_leases == 1
    assert store.get(expired.task_id).status.value == "running"
    assert snapshot.oldest_pending_age_seconds == 8.0


def test_prometheus_metrics_use_fixed_status_labels(tmp_path):
    snapshot = collect_task_metrics(TaskStore(tmp_path / "tasks.db"))

    output = render_prometheus(snapshot)

    assert 'corecoder_tasks{status="pending"} 0' in output
    assert "# TYPE corecoder_task_attempts counter" in output
    assert "task_id" not in output


def test_metrics_cli_supports_json(tmp_path, capsys):
    store_path = tmp_path / "tasks.db"
    TaskStore(store_path).enqueue("coding", {})

    assert main(["--store", str(store_path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_tasks"] == 1
    assert payload["pending_tasks"] == 1
