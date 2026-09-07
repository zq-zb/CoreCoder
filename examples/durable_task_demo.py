"""离线演示：任务入队、Worker 领取、Agent 执行和结果持久化。"""

import sys
import tempfile
from pathlib import Path

from corecoder.agent import Agent
from corecoder.llm import LLMResponse, ScriptedLLM
from corecoder.task_store import TaskStore
from corecoder.task_worker import DurableCodingWorker


def create_agent(task):
    return Agent(ScriptedLLM([LLMResponse(content="代码检查完成，本任务无需修改。")]), tools=[])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="corecoder-task-demo-") as directory:
        root = Path(directory)
        database = root / "tasks.db"
        store = TaskStore(database)

        pending = store.enqueue("coding", {"task": "检查代码结构", "workspace": str(root)})
        print(f"1. 任务入队：{pending.task_id} ({pending.status.value})")

        worker = DurableCodingWorker(store, "demo-worker", create_agent, lease_seconds=30)
        completed = worker.run_once()
        print(f"2. Worker 执行完成：{completed.status.value}")

        restored = TaskStore(database).get(pending.task_id)
        print(f"3. 新连接恢复任务：attempts={restored.attempts}, state={restored.result['state']}")
        print(f"4. Agent 结果：{restored.result['final_response']}")


if __name__ == "__main__":
    main()
