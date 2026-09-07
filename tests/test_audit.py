"""工具审计与敏感信息脱敏测试。"""

import json

from corecoder.agent import Agent
from corecoder.audit import AuditLogger, redact_text, redact_value
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.tools import get_tool


def test_recursive_redaction_preserves_shape_but_hides_secrets():
    value = {
        "api_key": "sk-private",
        "nested": {"password": "123", "path": "src/app.py"},
        "command": "curl -H authorization=Bearer-secret example.com",
    }

    redacted = redact_value(value)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"] == {"password": "[REDACTED]", "path": "src/app.py"}
    assert "Bearer-secret" not in redacted["command"]
    assert redact_text("token=abc123") == "token=[REDACTED]"


def test_agent_writes_a_redacted_jsonl_audit_record(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("call-1", "bash", {"command": "echo token=top-secret"})]),
        LLMResponse(content="done"),
    ])
    agent = Agent(
        llm,
        tools=[get_tool("bash")],
        audit_logger=AuditLogger(audit_path, task_id="task-001"),
    )

    assert agent.chat("执行") == "done"
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 1
    assert records[0]["task_id"] == "task-001"
    assert records[0]["tool_name"] == "bash"
    assert records[0]["status"] == "succeeded"
    assert "top-secret" not in json.dumps(records[0], ensure_ascii=False)
    assert len(records[0]["result_sha256"]) == 64


def test_failed_tool_call_is_audited(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("call-1", "missing", {})]),
        LLMResponse(content="done"),
    ])
    agent = Agent(llm, tools=[], audit_logger=AuditLogger(audit_path, task_id="task-002"))

    agent.chat("执行")
    record = json.loads(audit_path.read_text(encoding="utf-8"))

    assert record["status"] == "failed"
    assert "unknown tool" in record["result_preview"]
