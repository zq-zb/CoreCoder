"""持久化任务 CLI 测试。"""

from corecoder.task_cli import main
from corecoder.task_store import TaskStatus, TaskStore


def test_cli_enqueues_lists_and_cancels_task(tmp_path, capsys):
    database = tmp_path / "tasks.db"
    assert main([
        "--store",
        str(database),
        "enqueue",
        "--task",
        "检查代码",
        "--workspace",
        str(tmp_path),
    ]) == 0
    output = capsys.readouterr().out
    task_id = output.strip().split("：")[-1]

    assert main(["--store", str(database), "list", "--status", "pending"]) == 0
    assert task_id in capsys.readouterr().out

    assert main(["--store", str(database), "cancel", task_id]) == 0
    assert "cancelled" in capsys.readouterr().out
    assert TaskStore(database).get(task_id).status is TaskStatus.CANCELLED


def test_cli_rejects_missing_workspace(tmp_path, capsys):
    exit_code = main([
        "--store",
        str(tmp_path / "tasks.db"),
        "enqueue",
        "--task",
        "检查代码",
        "--workspace",
        str(tmp_path / "missing"),
    ])

    assert exit_code == 2
    assert "工作区不存在" in capsys.readouterr().out


def test_cli_recovers_expired_task(tmp_path, capsys):
    database = tmp_path / "tasks.db"
    now = [10.0]
    store = TaskStore(database, clock=lambda: now[0])
    store.enqueue("coding", {"task": "x", "workspace": str(tmp_path)})
    store.claim_next("dead-worker", lease_seconds=1)
    # CLI 使用真实时钟，因此测试数据的租约时间 11 已经确定过期。

    assert main(["--store", str(database), "recover"]) == 0
    assert "已回收 1" in capsys.readouterr().out
