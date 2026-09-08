"""持久化 Worker 与 Coding Agent 闭环测试。"""

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ScriptedLLM
from corecoder.task_store import TaskStatus, TaskStore
from corecoder.task_worker import DurableCodingWorker


def _simple_agent(task):
    return Agent(ScriptedLLM([LLMResponse(content="已分析，无需修改。")]), tools=[])


def test_worker_claims_runs_and_persists_coding_result(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {"task": "检查项目", "workspace": str(tmp_path)})
    worker = DurableCodingWorker(store, "worker-a", _simple_agent, lease_seconds=30)

    result = worker.run_once()

    assert result.task_id == task.task_id
    assert result.status is TaskStatus.SUCCEEDED
    assert result.result["state"] == "completed"
    assert result.result["final_response"] == "已分析，无需修改。"


def test_worker_persists_payload_validation_failure(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task = store.enqueue("coding", {"task": "缺少工作区"})
    worker = DurableCodingWorker(store, "worker-a", _simple_agent)

    result = worker.run_once()

    assert result.task_id == task.task_id
    assert result.status is TaskStatus.FAILED
    assert "必须包含" in result.last_error


def test_worker_rejects_unsupported_task_type(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    store.enqueue("email", {"text": "hello"})
    worker = DurableCodingWorker(store, "worker-a", _simple_agent)

    result = worker.run_once()

    assert result.status is TaskStatus.FAILED
    assert "不支持的任务类型" in result.last_error


def test_idle_worker_returns_none(tmp_path):
    worker = DurableCodingWorker(TaskStore(tmp_path / "tasks.db"), "worker-a", _simple_agent)

    assert worker.run_once() is None
