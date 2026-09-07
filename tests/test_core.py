"""Tests for core modules: config, context, session, imports."""

from corecoder import (
    ALL_TOOLS,
    LLM,
    Agent,
    Config,
    MCPManager,
    MCPRuntime,
    MCPRuntimeState,
    MCPServerConfig,
    __version__,
)
from corecoder import session as session_module
from corecoder.config import parse_config
from corecoder.context import CompressionLayer, ContextManager, estimate_tokens
from corecoder.llm import LLMResponse, ScriptedLLM, ToolCall
from corecoder.session import list_sessions, load_session, save_session
from corecoder.tools import get_tool


def test_version():
    assert __version__ == "0.4.0"


def test_public_api_exports():
    """Users should be able to import key classes from the top-level package."""
    assert Agent is not None
    assert LLM is not None
    assert Config is not None
    assert MCPRuntime is not None
    assert MCPRuntimeState is not None
    assert MCPManager is not None
    assert MCPServerConfig is not None
    assert len(ALL_TOOLS) == 10


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("CORECODER_MODEL", "test-model")
    c = Config.from_env()
    assert c.model == "test-model"


def test_config_defaults():
    # 显式传入空环境，避免开发者本地 .env 改变默认值测试结果。
    c = parse_config(env={})
    assert c.model == "gpt-5.5"
    assert c.max_tokens == 4096
    assert c.temperature == 0.0


# --- Context ---

def test_estimate_tokens():
    msgs = [{"role": "user", "content": "hello world"}]
    t = estimate_tokens(msgs)
    assert t > 0
    assert t < 100


def test_context_snip():
    ctx = ContextManager(max_tokens=3000)
    msgs = [
        {"role": "tool", "tool_call_id": "t1", "content": "x\n" * 1000},
    ]
    before = estimate_tokens(msgs)
    ctx._snip_tool_outputs(msgs)
    after = estimate_tokens(msgs)
    assert after < before


def test_context_snip_preserves_recent_tool_output():
    ctx = ContextManager(max_tokens=3000)
    old_output = "old\n" * 1000
    recent_output = "recent\n" * 1000
    messages = [
        {"role": "tool", "tool_call_id": "old", "content": old_output},
        {"role": "user", "content": "继续处理"},
        {"role": "assistant", "tool_calls": [{"id": "new"}]},
        {"role": "tool", "tool_call_id": "new", "content": recent_output},
    ]

    ctx._snip_tool_outputs(messages, preserve_recent=3)

    assert messages[0]["content"] != old_output
    assert messages[-1]["content"] == recent_output


def test_context_records_compression_metrics():
    ctx = ContextManager(max_tokens=1000)
    messages = [{"role": "user", "content": "请检查日志"}]
    for i in range(10):
        messages.extend([
            {"role": "assistant", "tool_calls": [{"id": f"t{i}"}]},
            {"role": "tool", "tool_call_id": f"t{i}", "content": "line\n" * 500},
        ])

    assert ctx.maybe_compress(messages, None) is True
    stats = ctx.stats()

    assert stats.compression_count >= 1
    assert stats.tokens_saved > 0
    assert stats.events_by_layer[CompressionLayer.TOOL_SNIP.value] == 1


def test_llm_summary_keeps_deterministic_working_memory():
    ctx = ContextManager(max_tokens=1000)
    llm = ScriptedLLM([LLMResponse(content="模型摘要")])
    messages = [
        {"role": "user", "content": "请修复 src/payment.py 并确保 pytest 通过"},
        {"role": "tool", "tool_call_id": "t1", "content": "Error: timeout"},
    ]

    summary = ctx._get_summary(messages, llm)

    assert "模型摘要" in summary
    assert "src/payment.py" in summary
    assert "Error: timeout" in summary
    assert "Latest user goal" in summary


def test_baseline_summary_does_not_append_structured_memory():
    ctx = ContextManager(max_tokens=1000, structured_memory=False)
    llm = ScriptedLLM([LLMResponse(content="仅保留模型摘要")])

    summary = ctx._get_summary([{"role": "user", "content": "修复 src/a.py"}], llm)

    assert summary == "仅保留模型摘要"


def test_agent_rejects_unknown_context_strategy():
    llm = ScriptedLLM([LLMResponse(content="unused")])

    try:
        Agent(llm, context_strategy="unknown")
    except ValueError as error:
        assert "未知上下文策略" in str(error)
    else:
        raise AssertionError("未知上下文策略必须被拒绝")


def test_agent_rejects_guided_retrieval_without_search_tool():
    llm = ScriptedLLM([LLMResponse(content="unused")])

    try:
        Agent(llm, tools=[get_tool("read_file")], repository_retrieval_policy="guided")
    except ValueError as error:
        assert "要求提供 repository_search" in str(error)
    else:
        raise AssertionError("guided 模式缺少检索工具时必须失败")


def test_guided_retrieval_rejects_broad_read_then_allows_search(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def target_symbol(): return True\n", encoding="utf-8")
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[ToolCall("read", "read_file", {"file_path": str(source)})]),
        LLMResponse(tool_calls=[ToolCall(
            "search", "repository_search", {"query": "target_symbol", "path": str(tmp_path)}
        )]),
        LLMResponse(tool_calls=[ToolCall("read2", "read_file", {"file_path": str(source)})]),
        LLMResponse(content="完成"),
    ])
    agent = Agent(
        llm,
        tools=[get_tool("repository_search"), get_tool("read_file")],
        repository_retrieval_policy="guided",
    )
    executed: list[str] = []

    assert agent.chat("定位目标", on_tool=lambda name, arguments: executed.append(name)) == "完成"
    replies = [message["content"] for message in agent.messages if message.get("role") == "tool"]
    assert replies[0].startswith("Policy: guided repository retrieval")
    assert "Repository context" in replies[1]
    assert "target_symbol" in replies[2]
    assert executed == ["repository_search", "read_file"]


def test_guided_retrieval_rejects_search_parallel_with_read(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def target_symbol(): return True\n", encoding="utf-8")
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[
            ToolCall("search", "repository_search", {"query": "target_symbol", "path": str(tmp_path)}),
            ToolCall("read", "read_file", {"file_path": str(source)}),
        ]),
        LLMResponse(content="已收到策略提示"),
    ])
    agent = Agent(
        llm,
        tools=[get_tool("repository_search"), get_tool("read_file")],
        repository_retrieval_policy="guided",
    )

    assert agent.chat("定位目标") == "已收到策略提示"
    replies = [message["content"] for message in agent.messages if message.get("role") == "tool"]
    assert len(replies) == 2
    assert all("run repository_search alone" in reply for reply in replies)


def test_context_compress():
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": "b" * 2000})
    before = estimate_tokens(msgs)
    ctx.maybe_compress(msgs, None)
    after = estimate_tokens(msgs)
    assert after < before
    assert len(msgs) < 40  # should be compressed


def test_safe_split_never_orphans_a_tool_message():
    """The kept tail must not begin with a 'tool' message - it would be severed
    from the assistant tool_calls that produced it, which the API rejects."""
    ctx = ContextManager(max_tokens=1000)
    messages = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "tool", "tool_call_id": "c2", "content": "result2"},
    ]
    split = ctx._safe_split(messages, keep_recent=1)
    assert messages[split].get("role") != "tool"


def test_compress_never_leaves_an_orphan_tool_reply():
    """After summarisation every tool reply must still follow its tool_calls."""
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "b" * 800})
    ctx.maybe_compress(msgs, None)
    for i, m in enumerate(msgs):
        if m.get("role") == "tool":
            prev = msgs[i - 1]
            assert prev.get("role") == "tool" or prev.get("tool_calls"), f"orphan tool at {i}"


# --- Session ---

def test_session_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    save_session(msgs, "test-model", "pytest_test_session")
    loaded = load_session("pytest_test_session")
    assert loaded is not None
    assert loaded[0] == msgs
    assert loaded[1] == "test-model"


def test_session_name_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    sid = save_session(msgs, "test-model", "../Research Notes!")

    assert sid == "Research-Notes"
    assert (tmp_path / "Research-Notes.json").exists()
    assert load_session("../Research Notes!") is not None


def test_session_not_found():
    assert load_session("nonexistent_session_id") is None


def test_list_sessions():
    sessions = list_sessions()
    assert isinstance(sessions, list)


# --- Cost estimation ---

def test_cost_estimation_known_model():
    from corecoder.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "gpt-5.4"
    llm.total_prompt_tokens = 1_000_000
    llm.total_completion_tokens = 500_000
    cost = llm.estimated_cost
    assert cost is not None
    assert cost == 2.5 + 7.5  # $2.5/M in + $15/M out * 0.5M

def test_cost_estimation_unknown_model():
    from corecoder.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "some-custom-model"
    llm.total_prompt_tokens = 1000
    llm.total_completion_tokens = 500
    assert llm.estimated_cost is None


# --- Changed files tracking ---

def test_edit_tracks_changed_files(tmp_path):
    from corecoder.tools.edit import _changed_files
    _changed_files.clear()
    edit = get_tool("edit_file")
    path = tmp_path / "sample.py"
    path.write_text("aaa\nbbb\n")
    edit.execute(file_path=str(path), old_string="aaa", new_string="zzz")
    assert any(str(path) in p for p in _changed_files)
    _changed_files.clear()


def test_write_tracks_changed_files(tmp_path):
    from corecoder.tools.edit import _changed_files
    _changed_files.clear()
    write = get_tool("write_file")
    path = tmp_path / "tracked.txt"
    write.execute(file_path=str(path), content="tracked\n")
    assert any(path.name in p for p in _changed_files)
    _changed_files.clear()


# --- Agent tool execution ---

def test_agent_tool_scope_is_per_instance():
    """An Agent restricted to a subset of tools must not resolve tools outside it."""
    only_read = [get_tool("read_file")]
    agent = Agent(llm=LLM.__new__(LLM), tools=only_read)
    assert set(agent._tool_by_name) == {"read_file"}

    class _TC:
        name = "bash"  # a real, registered tool - but not in this agent's set
        id = "x"
        arguments = {"command": "echo hi"}

    assert "unknown tool 'bash'" in agent._exec_tool(_TC())


def test_exec_tool_distinguishes_bad_args_from_internal_error():
    """A TypeError raised inside a tool must not be reported as bad arguments."""
    from corecoder.tools.base import Tool

    class _Boom(Tool):
        name = "boom"
        description = "raises TypeError internally"
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self):
            raise TypeError("internal explosion")

    agent = Agent(llm=LLM.__new__(LLM), tools=[_Boom()])

    class _BadArgs:
        name, id, arguments = "boom", "1", {"unexpected": 1}

    class _Good:
        name, id, arguments = "boom", "2", {}

    assert "bad arguments" in agent._exec_tool(_BadArgs())
    assert "Error executing boom" in agent._exec_tool(_Good())
    assert "bad arguments" not in agent._exec_tool(_Good())


def test_interrupt_backfills_missing_tool_replies():
    """A half-finished tool round must be repaired so history stays valid."""
    agent = Agent(llm=LLM.__new__(LLM), tools=[])
    agent.messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "done"},
    ]

    class _TC:
        def __init__(self, i):
            self.id = i

    agent._answer_pending_tool_calls([_TC("a"), _TC("b")])
    replies = [m for m in agent.messages if m.get("role") == "tool"]
    ids = [m["tool_call_id"] for m in replies]
    assert sorted(ids) == ["a", "b"]
    assert ids.count("a") == 1  # the already-answered call wasn't duplicated


def test_agent_recovers_from_one_empty_model_response():
    """Provider 偶发空响应时应请求模型继续，而不是把空内容当作完成。"""

    llm = ScriptedLLM([LLMResponse(), LLMResponse(content="已完成并验证。")])
    agent = Agent(llm, tools=[], max_rounds=3)

    assert agent.chat("修复问题") == "已完成并验证。"
    assert any("上一轮返回了空响应" in message.get("content", "") for message in agent.messages)


def test_agent_stops_after_two_empty_model_responses():
    agent = Agent(ScriptedLLM([LLMResponse(), LLMResponse()]), tools=[], max_rounds=3)

    assert agent.chat("修复问题") == "(model returned empty response twice)"
