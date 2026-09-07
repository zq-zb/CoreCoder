"""工具调用审计：结构化记录、敏感信息脱敏和并发安全写入。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|token|password|secret|authorization|cookie)", re.IGNORECASE)
_INLINE_SECRET = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*([^\s,;&]+)"
)


@dataclass(frozen=True)
class AuditRecord:
    """一条不可执行、便于检索的工具审计记录。"""

    timestamp_utc: str
    task_id: str
    tool_name: str
    status: str
    duration_ms: float
    arguments: dict[str, Any]
    result_preview: str
    result_sha256: str


class AuditLogger:
    """将调用记录追加为 JSONL；单条写入由锁保护。"""

    def __init__(self, path: str | Path, *, task_id: str, preview_limit: int = 500) -> None:
        if not task_id.strip():
            raise ValueError("审计 task_id 不能为空")
        if preview_limit < 0:
            raise ValueError("审计预览长度不能小于 0")
        self.path = Path(path).expanduser().resolve()
        self.task_id = task_id
        self.preview_limit = preview_limit
        self._lock = threading.Lock()

    def record(self, tool_name: str, arguments: dict[str, Any], result: str, duration_seconds: float) -> None:
        safe_result = redact_text(result)
        record = AuditRecord(
            timestamp_utc=datetime.now(UTC).isoformat(),
            task_id=self.task_id,
            tool_name=tool_name,
            status=_result_status(result),
            duration_ms=round(max(0.0, duration_seconds) * 1000, 3),
            arguments=redact_value(arguments),
            result_preview=safe_result[: self.preview_limit],
            result_sha256=hashlib.sha256(result.encode("utf-8", errors="replace")).hexdigest(),
        )
        line = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")


def redact_value(value: Any) -> Any:
    """递归脱敏参数；保留结构，隐藏凭据内容。"""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """隐藏字符串中常见的 key=value 形式凭据。"""

    return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def _result_status(result: str) -> str:
    lowered = result.lstrip().lower()
    if lowered.startswith(("error:", "⚠ blocked", "⚠ approval required")) or re.search(
        r"\[exit code:\s*[1-9]", lowered
    ):
        return "failed"
    return "succeeded"
