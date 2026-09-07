"""把持久化任务台账与 CodingTaskRunner 连接起来。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .agent import Agent
from .coding_task import CodingTaskRunner, CodingTaskState
from .task_store import TaskRecord, TaskStatus, TaskStore

AgentFactory = Callable[[TaskRecord], Agent]


class DurableCodingWorker:
    """一次领取并执行一个 Coding 任务，适合被服务循环反复调用。"""

    def __init__(
        self,
        store: TaskStore,
        worker_id: str,
        agent_factory: AgentFactory,
        *,
        lease_seconds: float = 60,
    ) -> None:
        if not worker_id.strip() or lease_seconds <= 0:
            raise ValueError("Worker ID 不能为空，租约时间必须大于 0")
        self.store = store
        self.worker_id = worker_id.strip()
        self.agent_factory = agent_factory
        self.lease_seconds = lease_seconds

    def run_once(self) -> TaskRecord | None:
        task = self.store.claim_next(self.worker_id, lease_seconds=self.lease_seconds)
        if task is None:
            return None
        stop = threading.Event()
        heartbeat_error: list[str] = []
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(task.task_id, stop, heartbeat_error),
            name=f"corecoder-heartbeat-{task.task_id[:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            record = self._execute(task)
        except Exception as error:
            current = self.store.get(task.task_id)
            if current.status is TaskStatus.CANCEL_REQUESTED:
                record = self.store.acknowledge_cancel(task.task_id, self.worker_id)
            elif current.status is TaskStatus.RUNNING:
                record = self.store.finish(
                    task.task_id,
                    self.worker_id,
                    succeeded=False,
                    error=f"Worker 执行异常：{error}",
                )
            else:
                record = current
        finally:
            stop.set()
            heartbeat.join(timeout=min(2.0, self.lease_seconds))
        if heartbeat_error and record.status is TaskStatus.SUCCEEDED:
            # 任务已经原子落为成功，心跳尾部告警不应反向篡改终态；
            # 生产监控应单独上报 heartbeat_error。
            return record
        return record

    def _execute(self, task: TaskRecord) -> TaskRecord:
        if task.task_type != "coding":
            return self.store.finish(
                task.task_id,
                self.worker_id,
                succeeded=False,
                error=f"不支持的任务类型：{task.task_type}",
            )
        instruction = task.payload.get("task")
        workspace = task.payload.get("workspace")
        if not isinstance(instruction, str) or not instruction.strip() or not isinstance(workspace, str):
            return self.store.finish(
                task.task_id,
                self.worker_id,
                succeeded=False,
                error="coding 任务必须包含非空 task 和 workspace",
            )

        agent = self.agent_factory(task)

        def check_cancel(name: str, arguments: dict) -> None:
            if self.store.get(task.task_id).status is TaskStatus.CANCEL_REQUESTED:
                raise RuntimeError("任务已请求取消")

        report = CodingTaskRunner(agent, Path(workspace)).run(instruction, on_tool=check_cancel)
        current = self.store.get(task.task_id)
        if current.status is TaskStatus.CANCEL_REQUESTED:
            return self.store.acknowledge_cancel(task.task_id, self.worker_id)
        succeeded = report.state is CodingTaskState.COMPLETED
        result = {
            "state": report.state.value,
            "verified": report.verified,
            "changed_files": list(report.changed_files),
            "test_runs": len(report.test_runs),
            "final_response": report.final_response,
        }
        return self.store.finish(
            task.task_id,
            self.worker_id,
            succeeded=succeeded,
            result=result,
            error=report.failure_reason,
        )

    def _heartbeat_loop(self, task_id: str, stop: threading.Event, errors: list[str]) -> None:
        interval = max(0.1, self.lease_seconds / 3)
        while not stop.wait(interval):
            try:
                self.store.heartbeat(task_id, self.worker_id, lease_seconds=self.lease_seconds)
            except ValueError as error:
                # 任务结束或被其他控制面回收后停止续租。
                errors.append(str(error))
                return
