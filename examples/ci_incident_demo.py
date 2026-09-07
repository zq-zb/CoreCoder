"""离线演示：从 GitHub Actions 失败到修复、验收和事故报告。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from corecoder.agent import Agent
from corecoder.audit import AuditLogger
from corecoder.incident import CIIncidentCoordinator, write_incident_report
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.task_store import TaskStore
from corecoder.task_worker import DurableCodingWorker
from corecoder.tools import get_tool


class DemoFailureSource:
    """模拟 GitHub 只读接口，使演示不依赖网络和真实仓库。"""

    def get_workflow_run_failure(self, repository: str, run_id: int):
        return {
            "repository": repository,
            "run_id": run_id,
            "failed_jobs": [
                {
                    "name": "python-tests",
                    "conclusion": "failure",
                    "failed_steps": [{"number": 3, "name": "unit tests", "conclusion": "failure"}],
                }
            ],
            "failed_logs": "AssertionError: add(2, 3) expected 5 but got -1",
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    workspace = root / ".corecoder" / "ci-incident-demo" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "calculator.py"
    test_file = workspace / "test_calculator.py"
    # 每次重置演示夹具，保证可以重复运行并得到相同的故障路径。
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    test_file.write_text(
        "import unittest\nfrom calculator import add\n\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    command = f'cd /d "{workspace}" && "{sys.executable}" -B -m unittest "{test_file.name}"'
    scripted = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall("read", "read_file", {"file_path": str(source)})]),
            LLMResponse(tool_calls=[ToolCall("test-before", "bash", {"command": command})]),
            LLMResponse(tool_calls=[ToolCall("fix", "edit_file", {
                "file_path": str(source),
                "old_string": "    return a - b",
                "new_string": "    return a + b",
            })]),
            LLMResponse(tool_calls=[ToolCall("test-after", "bash", {"command": command})]),
            LLMResponse(content="定位为加法实现错误，已最小修复并通过回归测试。"),
        ]
    )
    # 临时任务库让每次演示都是一次新事故，避免旧幂等记录与重置后的夹具冲突。
    temporary = tempfile.TemporaryDirectory(prefix="corecoder-ci-demo-")
    store = TaskStore(Path(temporary.name) / "tasks.db")
    coordinator = CIIncidentCoordinator(
        store,
        source=DemoFailureSource(),
        audit_dir=root / ".corecoder" / "ci-incident-demo" / "audit",
    )
    intake = coordinator.ingest("demo/corecoder", 20260907, workspace)

    def agent_factory(task):
        return Agent(
            scripted,
            tools=[get_tool("read_file"), get_tool("edit_file"), get_tool("bash")],
            audit_logger=AuditLogger(coordinator.audit_path(task.task_id), task_id=task.task_id),
        )

    DurableCodingWorker(store, "ci-incident-demo-worker", agent_factory).run_once()
    report = coordinator.build_report(intake.task_id)
    _, markdown = write_incident_report(report, root / "evals" / "reports" / "incidents")
    print(f"事故：{report.incident_id}")
    print(f"任务状态：{report.task_status}，验证：{report.verified}")
    print(f"测试次数：{report.test_runs}，审计记录：{report.audit_records}")
    print(f"报告：{markdown}")
    temporary.cleanup()
    return 0 if report.task_status == "succeeded" and report.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
