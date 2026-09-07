"""Core agent loop.

This is the heart of CoreCoder.  The pattern is simple:

    user message -> LLM (with tools) -> tool calls? -> execute -> loop
                                      -> text reply? -> return to user

It keeps looping until the LLM responds with plain text (no tool calls),
which means it's done working and ready to report back.
"""

import concurrent.futures
import inspect
import time

from .audit import AuditLogger
from .context import ContextManager
from .llm import LLM
from .prompt import system_prompt
from .tools import create_default_tools
from .tools.agent import AgentTool
from .tools.base import Tool


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
        context_strategy: str = "structured-memory",
        repository_retrieval_policy: str = "available",
        audit_logger: AuditLogger | None = None,
    ):
        self.llm = llm
        self.tools = tools if tools is not None else create_default_tools()
        self._tool_by_name = {t.name: t for t in self.tools}
        self.messages: list[dict] = []
        if context_strategy not in {"baseline", "structured-memory"}:
            raise ValueError(f"未知上下文策略：{context_strategy}")
        self.context_strategy = context_strategy
        if repository_retrieval_policy not in {"available", "guided"}:
            raise ValueError(f"未知仓库检索策略：{repository_retrieval_policy}")
        if repository_retrieval_policy == "guided" and "repository_search" not in self._tool_by_name:
            raise ValueError("guided 检索策略要求提供 repository_search 工具")
        self.repository_retrieval_policy = repository_retrieval_policy
        self.context = ContextManager(
            max_tokens=max_context_tokens,
            structured_memory=context_strategy == "structured-memory",
        )
        self.max_rounds = max_rounds
        self.audit_logger = audit_logger
        self._system = system_prompt(self.tools, repository_retrieval_policy=repository_retrieval_policy)

        # wire up sub-agent capability
        # 构造 Agent 时，把自己传给 AgentTool，方便子 Agent 继承父 Agent 的 LLM、工具、上下文限制
        for t in self.tools:
            if isinstance(t, AgentTool):
                t._parent_agent = self

    def _full_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system}] + self.messages

    def _tool_schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools]

    def chat(self, user_input: str, on_token=None, on_tool=None, on_tool_result=None) -> str:
        """Process one user message. May involve multiple LLM/tool rounds."""
        self.messages.append({"role": "user", "content": user_input}) # 内容加进对话历史
        self.context.maybe_compress(self.messages, self.llm) # 压缩对话历史，防止超过最大上下文长度

        empty_responses = 0
        retrieval_satisfied = self.repository_retrieval_policy != "guided"
        for _ in range(self.max_rounds):
            # 对话历史 + 工具信息 -> LLM -> 可能的工具调用
            resp = self.llm.chat(
                messages=self._full_messages(),
                tools=self._tool_schemas(),
                on_token=on_token,
            )

            # no tool calls -> LLM is done, return text
            if not resp.tool_calls: # 没有工具调用、LLM 已完成，结束任务
                if not resp.content.strip():
                    empty_responses += 1
                    self.messages.append({"role": "assistant", "content": "[empty response]"})
                    if empty_responses >= 2:
                        return "(model returned empty response twice)"
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "你上一轮返回了空响应。请根据当前任务继续执行必要工具；"
                            "如果已经完成，请明确说明修改内容和测试结果。"
                        ),
                    })
                    continue
                self.messages.append(resp.message)
                return resp.content

            # 工具调用 执行
            # tool calls -> execute (parallel when multiple, like Claude Code's
            # StreamingToolExecutor which runs independent tools concurrently)
            self.messages.append(resp.message)

            if not retrieval_satisfied:
                has_search = any(call.name == "repository_search" for call in resp.tool_calls)
                has_parallel_inspection = any(
                    call.name in _REPOSITORY_INSPECTION_TOOLS for call in resp.tool_calls
                )
                if has_search and has_parallel_inspection:
                    # 首次检索不能与读取/修改并行，否则后者并没有消费检索结果。
                    for tc in resp.tool_calls:
                        result = (
                            "Policy: run repository_search alone as the first repository operation; "
                            "inspect or edit its ranked results in the next tool round."
                        )
                        self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    continue
                if has_search:
                    retrieval_satisfied = True
                elif has_parallel_inspection:
                    # 提示词是软约束，部分模型仍会先广泛读取。guided 模式在执行层
                    # 拒绝第一次旁路检查，让实验能确定性地真正使用检索能力。
                    for tc in resp.tool_calls:
                        result = (
                            "Policy: guided repository retrieval requires repository_search before "
                            "bash/glob/grep/read/write operations. Search by the task's error, symbol, "
                            "or behavior first, then inspect the strongest results."
                        )
                        self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    continue

            try:
                if len(resp.tool_calls) == 1:
                    tc = resp.tool_calls[0]
                    if on_tool:
                        on_tool(tc.name, tc.arguments)
                    # 每个工具调用都执行一次，返回结果，追加到对话历史
                    result = self._exec_tool(tc)
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                    self.messages.append(tool_message)
                    if on_tool_result:
                        control_feedback = on_tool_result(tc.name, tc.arguments, result)
                        if isinstance(control_feedback, str) and control_feedback:
                            tool_message["content"] += f"\n\n[CoreCoder control]\n{control_feedback}"
                else:
                    # parallel execution for multiple tool calls
                    # 如果有多个工具调用，则并行执行，返回结果，追加到对话历史
                    results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                    for tc, result in zip(resp.tool_calls, results):
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                        self.messages.append(tool_message)
                        if on_tool_result:
                            control_feedback = on_tool_result(tc.name, tc.arguments, result)
                            if isinstance(control_feedback, str) and control_feedback:
                                tool_message["content"] += f"\n\n[CoreCoder control]\n{control_feedback}"
            except KeyboardInterrupt: # 异常中断
                # Ctrl+C mid-execution would leave the assistant tool_calls
                # message without replies, poisoning the next request; backfill
                self._answer_pending_tool_calls(resp.tool_calls)
                raise

            # compress if tool outputs are big
            self.context.maybe_compress(self.messages, self.llm)

        return "(reached maximum tool-call rounds)"

    def _exec_tool(self, tc) -> str:
        """Execute a single tool call, returning the result string."""
        started = time.perf_counter()
        result = self._execute_tool(tc)
        if self.audit_logger:
            self.audit_logger.record(tc.name, tc.arguments, result, time.perf_counter() - started)
        return result

    def _execute_tool(self, tc) -> str:
        """执行工具并把所有失败转换成稳定的文本结果。"""
        # 工具调用的名称和参数
        tool = self._tool_by_name.get(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"
        # validate arguments first so a TypeError raised *inside* the tool isn't
        # mislabelled as a bad-arguments error from the caller
        try: # 尝试一次参数绑定，确保参数正确
            # 区分 参数错误 or 工具执行错误
            inspect.signature(tool.execute).bind(**tc.arguments) # 参数能否对上签名
        except TypeError as e:
            return f"Error: bad arguments for {tc.name}: {e}"
        try:
            return tool.execute(**tc.arguments)
        except Exception as e:
            return f"Error executing {tc.name}: {e}"

    def _exec_tools_parallel(self, tool_calls, on_tool=None) -> list[str]:
        """Run multiple tool calls concurrently using threads.

        This is inspired by Claude Code's StreamingToolExecutor which starts
        executing tools while the model is still generating.  We simplify to:
        when the model returns N tool calls at once, run them in parallel.
        """
        # 执行多个工具调用，返回结果列表
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)
        # 线程池
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._exec_tool, tc) for tc in tool_calls]
            return [f.result() for f in futures]
        # 问题点
        # 边生成边执行，模型还在吐后面内容时，程序工具调用先跑，不必等整段响应结束
        # 区分工具安全不安全并发，只读工具可以，写工具要小心，可能需要加锁或排队。

    def _answer_pending_tool_calls(self, tool_calls):
        """Backfill a tool reply for every call that didn't get one.

        OpenAI-compatible APIs reject a request where an assistant message has
        tool_calls without a matching tool reply for each id, so this keeps the
        history valid when execution is interrupted partway through.
        """
        # 给每个没有得到回复的工具调用添加一个 "[interrupted]" 的回复，确保对话历史有效
        # 收集已回复的 ID，给缺的补占位
        answered = {m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"}
        for tc in tool_calls:
            if tc.id not in answered:
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "[interrupted]",
                })

    def reset(self):
        """Clear conversation history."""
        self.messages.clear()


_REPOSITORY_INSPECTION_TOOLS = {
    "bash", "glob", "grep", "read_file", "edit_file", "write_file",
}
