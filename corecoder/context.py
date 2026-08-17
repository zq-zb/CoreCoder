"""Multi-layer context compression.

Claude Code uses a 4-layer strategy:
  1. HISTORY_SNIP   - trim old tool outputs to a one-line summary
  2. Microcompact   - LLM-powered summary of old turns (cached)
  3. CONTEXT_COLLAPSE - aggressive compression when nearing hard limit
  4. Autocompact    - periodic background compaction

CoreCoder implements the same idea in 3 layers:
  Layer 1 (tool_snip)   - replace verbose tool results with truncated versions
  Layer 2 (summarize)   - LLM-powered summary of old conversation
  Layer 3 (hard_collapse) - last resort: drop everything except summary + recent
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLM


def _approx_tokens(text: str) -> int:
    """Rough token count, roughly 3 chars per token for mixed en/zh content."""
    return len(text) // 3

# 估算 token 字符数除以3 够用就好 判断的是粗略值
def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        if m.get("content"):
            total += _approx_tokens(m["content"])
        if m.get("tool_calls"):
            total += _approx_tokens(str(m["tool_calls"]))
    return total


class ContextManager:
    def __init__(self, max_tokens: int = 128_000):
        self.max_tokens = max_tokens
        # layer thresholds (fraction of max_tokens)
        # 三层比例
        self._snip_at = int(max_tokens * 0.50)    # 50% -> snip tool outputs
        self._summarize_at = int(max_tokens * 0.70)  # 70% -> LLM summarize
        self._collapse_at = int(max_tokens * 0.90)   # 90% -> hard collapse
    # 估算用的 token 数量，粗略计算，混合中英文大约 3 个字符算一个 token
    def maybe_compress(self, messages: list[dict], llm: LLM | None = None) -> bool:
        """Apply compression layers as needed. Returns True if any compression happened."""
        current = estimate_tokens(messages)
        compressed = False

        # 第一层：旧的工具输出过长，截断为首尾几行
        # Layer 1: snip verbose tool outputs
        if current > self._snip_at:
            if self._snip_tool_outputs(messages):
                compressed = True
                current = estimate_tokens(messages)

        # 第二层：旧对话写个摘要
        # Layer 2: LLM-powered summarization of old turns
        if current > self._summarize_at and len(messages) > 10: 
            if self._summarize_old(messages, llm, keep_recent=8): # 留最近 8 条消息原样不动
                compressed = True
                current = estimate_tokens(messages)

        # Layer 3: hard collapse - last resort
        # 第三层：只保留最后几条消息 + 摘要，丢掉其他所有内容
        if current > self._collapse_at and len(messages) > 4:
            self._hard_collapse(messages, llm)
            compressed = True

        return compressed

    @staticmethod
    def _snip_tool_outputs(messages: list[dict]) -> bool:
        """Layer 1: Truncate tool results over 1500 chars to their first/last lines.

        This mirrors Claude Code's HISTORY_SNIP which replaces old tool outputs
        with a one-line summary to reclaim context space.
        """
        # 纯文本处理：超过 1500 字符的工具输出，截断为首尾各三行，中间省略
        changed = False
        for m in messages:
            if m.get("role") != "tool":
                continue
            content = m.get("content", "")
            if len(content) <= 1500:
                continue
            lines = content.splitlines()
            if len(lines) <= 6:
                continue
            # keep first 3 + last 3 lines
            snipped = (
                "\n".join(lines[:3])
                + f"\n... ({len(lines)} lines, snipped to save context) ...\n"
                + "\n".join(lines[-3:])
            )
            m["content"] = snipped
            changed = True
        return changed

    @staticmethod
    def _safe_split(messages: list[dict], keep_recent: int) -> int:
        """Index where the kept tail should start.

        Walk the boundary back so a 'tool' result is never separated from the
        assistant message whose tool_calls produced it - an orphaned tool
        message has no preceding tool_calls and OpenAI-compatible APIs reject it.
        """
        # 安全切分计算
        # 绝对不能把 tool 回复消息和它对应的、带 tool_calls 的 assistant 消息切开
        split = max(0, len(messages) - keep_recent) # 起始切分索引
        # 切分位置的消息 不是 tool
        while split > 0 and messages[split].get("role") == "tool":
            split -= 1
        return split

    def _summarize_old(self, messages: list[dict], llm: LLM | None,
                       keep_recent: int = 8) -> bool:
        """Layer 2: Summarize old conversation, keep recent messages intact."""
        if len(messages) <= keep_recent:
            return False

        split = self._safe_split(messages, keep_recent)
        old = messages[:split]
        tail = messages[split:]

        summary = self._get_summary(old, llm)

        messages.clear()
        messages.append({
            "role": "user",
            "content": f"[Context compressed - conversation summary]\n{summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "Got it, I have the context from our earlier conversation.",
        })
        messages.extend(tail)
        return True

    def _hard_collapse(self, messages: list[dict], llm: LLM | None):
        """Layer 3: Emergency compression. Keep only last 4 messages + summary."""
        split = self._safe_split(messages, 4 if len(messages) > 4 else 2)
        tail = messages[split:]
        summary = self._get_summary(messages[:split], llm)

        messages.clear()
        messages.append({
            "role": "user",
            "content": f"[Hard context reset]\n{summary}",
        })
        messages.append({
            "role": "assistant",
            "content": "Context restored. Continuing from where we left off.",
        })
        messages.extend(tail)

    def _get_summary(self, messages: list[dict], llm: LLM | None) -> str:
        """Generate summary via LLM or fallback to extraction."""
        flat = self._flatten(messages)
        # 保留改过的文件路径、做过的关键决定、遇到的错误、当前任务状态；
        #   丢掉啰嗦的命令输出、代码清单、来回的废话。这正是一个长任务里真正需要被记住的东西。
        if llm:
            try:
                resp = llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Compress this conversation into a brief summary. "
                                "Preserve: file paths edited, key decisions made, "
                                "errors encountered, current task state. "
                                "Drop: verbose command output, code listings, "
                                "redundant back-and-forth."
                            ),
                        },
                        {"role": "user", "content": flat[:15000]},
                    ],
                )
                return resp.content
            except Exception:
                pass

        # fallback: extract key lines
        # 没有可用模型：退化成提取关键行，保留文件路径、错误、决策
        # 用正则把文件路径和带 error 的行抽出来拼一个粗摘要。
        return self._extract_key_info(messages)

    @staticmethod
    def _flatten(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "?")
            text = m.get("content", "") or ""
            if text:
                parts.append(f"[{role}] {text[:400]}")
        return "\n".join(parts)

    @staticmethod
    def _extract_key_info(messages: list[dict]) -> str:
        """Fallback: extract file paths, errors, and decisions without LLM."""
        # 压缩降级处理方案：不调大模型，0 token 成本
        # 「操作过的文件」和「出现过的错误」，生成一份极简摘要
        import re
        files_seen = set()
        errors = []

        for m in messages:
            text = m.get("content", "") or ""
            # extract file paths
            # 粗略地把文件路径提取出来，作为文件操作摘要
            for match in re.finditer(r'[\w./\-]+\.\w{1,5}', text):
                files_seen.add(match.group())
            # extract error lines
            # 粗略地把包含 error 的行提取出来，作为错误摘要
            for line in text.splitlines():
                if "error" in line.lower():
                    errors.append(line.strip()[:150])

        parts = []
        # 拼接结果，文件最多 20 个，错误最多 5 个
        if files_seen:
            parts.append(f"Files touched: {', '.join(sorted(files_seen)[:20])}")
        if errors:
            parts.append(f"Errors seen: {'; '.join(errors[:5])}")
        return "\n".join(parts) or "(no extractable context)"
