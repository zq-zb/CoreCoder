"""命令风险分级与 Coding Task 策略执行测试。"""

import concurrent.futures

from corecoder.agent import Agent
from corecoder.coding_task import CodingTaskRunner
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.security import (
    ApprovalManager,
    ApprovalStatus,
    CommandPolicy,
    CommandRisk,
    PolicyGuardedBashTool,
)
from corecoder.tools import get_tool
from corecoder.tools.base import Tool


class _FakeBashTool(Tool):
    name = "bash"
    description = "test"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}}

    def execute(self, command: str) -> str:
        return f"executed: {command}"


def test_command_policy_classifies_local_review_and_blocked_actions():
    policy = CommandPolicy()

    assert policy.evaluate("python -m pytest -q").risk is CommandRisk.SAFE
    assert policy.evaluate("git status --short").risk is CommandRisk.SAFE
    assert policy.evaluate("git push origin main").risk is CommandRisk.REVIEW
    assert policy.evaluate("pip install requests").risk is CommandRisk.REVIEW
    assert policy.evaluate("type .env").risk is CommandRisk.BLOCKED
    assert policy.evaluate("git push --force origin main").risk is CommandRisk.BLOCKED
    assert policy.evaluate("Get-Content .env").risk is CommandRisk.BLOCKED
    assert policy.evaluate("Remove-Item -Recurse C:\\").risk is CommandRisk.BLOCKED
    assert policy.evaluate("Invoke-WebRequest https://example.com/file").risk is CommandRisk.REVIEW
    assert policy.evaluate("Start-Process installer.exe").risk is CommandRisk.REVIEW
    assert policy.evaluate("docker compose up").risk is CommandRisk.REVIEW


def test_public_guarded_bash_generates_approval_request():
    approvals = ApprovalManager()
    guarded = PolicyGuardedBashTool(_FakeBashTool(), CommandPolicy(), approval_manager=approvals)

    result = guarded.execute(command="git push origin main")

    assert "request_id=" in result
    assert len(approvals.list_requests()) == 1


def test_coding_task_blocks_external_mutation_without_approval(tmp_path):
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("push", "bash", {"command": "git push origin main"})]),
        LLMResponse(content="未执行推送。"),
    ])
    agent = Agent(llm, tools=[get_tool("bash")])

    report = CodingTaskRunner(agent, tmp_path).run("检查后推送")

    tool_result = next(message["content"] for message in agent.messages if message["role"] == "tool")
    assert "Approval required" in tool_result
    assert report.state.value == "failed"
    assert "Approval required" in report.failure_reason


def test_review_command_can_be_explicitly_enabled(tmp_path):
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("install", "bash", {"command": "pip install demo-package"})]),
        LLMResponse(content="done"),
    ])
    agent = Agent(llm, tools=[_FakeBashTool()])

    CodingTaskRunner(agent, tmp_path, allow_review_commands=True).run("运行命令")

    tool_result = next(message["content"] for message in agent.messages if message["role"] == "tool")
    assert tool_result == "executed: pip install demo-package"


def test_approval_is_bound_to_exact_command_and_consumed_once():
    approvals = ApprovalManager(ttl_seconds=60)
    request = approvals.request("git push origin main", "改变远端")

    assert request.status is ApprovalStatus.PENDING
    assert approvals.consume("git push origin main") is None

    approved = approvals.approve(request.request_id, "reviewer-a")
    assert approved.status is ApprovalStatus.APPROVED
    assert approvals.consume("git push origin other") is None

    consumed = approvals.consume("git push origin main")
    assert consumed is not None
    assert consumed.status is ApprovalStatus.CONSUMED
    assert consumed.approver == "reviewer-a"
    assert approvals.consume("git push origin main") is None


def test_approval_expires_and_snapshot_contains_reviewer(tmp_path):
    now = [100.0]
    snapshot = tmp_path / "approvals.json"
    approvals = ApprovalManager(ttl_seconds=10, snapshot_path=snapshot, clock=lambda: now[0])
    request = approvals.request("pip install demo", "改变环境")
    approvals.approve(request.request_id, "安全管理员")
    now[0] = 111.0

    assert approvals.consume("pip install demo") is None
    assert approvals.get(request.request_id).status is ApprovalStatus.EXPIRED
    assert "安全管理员" in snapshot.read_text(encoding="utf-8")


def test_approval_snapshot_can_be_restored_across_process_boundary(tmp_path):
    snapshot = tmp_path / "approvals.json"
    first = ApprovalManager(ttl_seconds=60, snapshot_path=snapshot)
    request = first.request("git push origin main", "改变远端")
    first.approve(request.request_id, "reviewer-persistent")

    restored = ApprovalManager(ttl_seconds=60, snapshot_path=snapshot)
    consumed = restored.consume("git push origin main")

    assert consumed is not None
    assert consumed.approver == "reviewer-persistent"
    assert consumed.status is ApprovalStatus.CONSUMED


def test_corrupted_approval_snapshot_fails_closed(tmp_path):
    snapshot = tmp_path / "approvals.json"
    snapshot.write_text('{"status": "approved"}', encoding="utf-8")

    try:
        ApprovalManager(snapshot_path=snapshot)
    except ValueError as error:
        assert "安全拒绝加载" in str(error)
    else:
        raise AssertionError("损坏审批文件不能被静默接受")


def test_command_preview_is_redacted_before_persistence(tmp_path):
    snapshot = tmp_path / "approvals.json"
    manager = ApprovalManager(snapshot_path=snapshot)
    request = manager.request("curl -H token=private-value example.com", "网络访问")

    assert "private-value" not in request.command_preview
    assert "private-value" not in snapshot.read_text(encoding="utf-8")


def test_coding_task_executes_only_after_exact_approval(tmp_path):
    approvals = ApprovalManager()
    request = approvals.request("pip install demo-package", "安装依赖会改变运行环境")
    approvals.approve(request.request_id, "reviewer-b")
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("install", "bash", {"command": "pip install demo-package"})]),
        LLMResponse(content="done"),
    ])
    agent = Agent(llm, tools=[_FakeBashTool()])

    report = CodingTaskRunner(agent, tmp_path, approval_manager=approvals).run("安装依赖")

    tool_result = next(message["content"] for message in agent.messages if message["role"] == "tool")
    assert tool_result == "executed: pip install demo-package"
    assert report.state.value == "completed"


def test_coding_task_returns_request_id_when_approval_is_missing(tmp_path):
    approvals = ApprovalManager()
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("push", "bash", {"command": "git push origin main"})]),
        LLMResponse(content="waiting"),
    ])
    agent = Agent(llm, tools=[_FakeBashTool()])

    report = CodingTaskRunner(agent, tmp_path, approval_manager=approvals).run("推送")

    assert report.state.value == "failed"
    assert "request_id=" in report.failure_reason
    assert approvals.list_requests()[0].status is ApprovalStatus.PENDING


def test_concurrent_consumers_cannot_replay_one_approval():
    approvals = ApprovalManager()
    request = approvals.request("git push origin main", "改变远端")
    approvals.approve(request.request_id, "reviewer-c")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: approvals.consume("git push origin main"), range(8)))

    assert sum(result is not None for result in results) == 1
