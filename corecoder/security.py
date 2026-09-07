"""命令风险分级策略，区分本地开发动作与外部状态变更。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path

from .audit import redact_text
from .tools.base import Tool


class CommandRisk(str, Enum):
    SAFE = "safe"
    REVIEW = "review"
    BLOCKED = "blocked"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class CommandDecision:
    risk: CommandRisk
    reason: str

    @property
    def allowed_without_approval(self) -> bool:
        return self.risk is CommandRisk.SAFE


@dataclass(frozen=True)
class ApprovalRequest:
    """只对命令原文指纹生效的一次性审批单。"""

    request_id: str
    command_sha256: str
    command_preview: str
    reason: str
    status: ApprovalStatus
    created_at: float
    expires_at: float
    approver: str | None = None
    approved_at: float | None = None
    consumed_at: float | None = None


class ApprovalManager:
    """管理有时限、绑定命令且只能使用一次的审批。"""

    def __init__(
        self,
        *,
        ttl_seconds: float = 300,
        snapshot_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("审批有效期必须大于 0")
        self.ttl_seconds = ttl_seconds
        self.snapshot_path = Path(snapshot_path).resolve() if snapshot_path else None
        self._clock = clock
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._load_snapshot()

    def request(self, command: str, reason: str) -> ApprovalRequest:
        digest = _command_digest(command)
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            for request in self._requests.values():
                if request.command_sha256 == digest and request.status is ApprovalStatus.PENDING:
                    return request
            request = ApprovalRequest(
                request_id=uuid.uuid4().hex,
                command_sha256=digest,
                command_preview=redact_text(command.strip())[:500],
                reason=reason,
                status=ApprovalStatus.PENDING,
                created_at=now,
                expires_at=now + self.ttl_seconds,
            )
            self._requests[request.request_id] = request
            self._persist_locked()
            return request

    def approve(self, request_id: str, approver: str) -> ApprovalRequest:
        if not approver.strip():
            raise ValueError("审批人不能为空")
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            request = self._requests.get(request_id)
            if request is None:
                raise KeyError(f"审批单不存在：{request_id}")
            if request.status is not ApprovalStatus.PENDING:
                raise ValueError(f"审批单状态不允许批准：{request.status.value}")
            approved = replace(
                request,
                status=ApprovalStatus.APPROVED,
                approver=approver.strip(),
                approved_at=now,
            )
            self._requests[request_id] = approved
            self._persist_locked()
            return approved

    def consume(self, command: str) -> ApprovalRequest | None:
        """原子消费完全匹配的批准；相同批准不能重放。"""

        digest = _command_digest(command)
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            for request_id, request in self._requests.items():
                if request.command_sha256 == digest and request.status is ApprovalStatus.APPROVED:
                    consumed = replace(request, status=ApprovalStatus.CONSUMED, consumed_at=now)
                    self._requests[request_id] = consumed
                    self._persist_locked()
                    return consumed
            return None

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock:
            self._expire_locked(self._clock())
            return self._requests.get(request_id)

    def list_requests(self) -> tuple[ApprovalRequest, ...]:
        with self._lock:
            self._expire_locked(self._clock())
            return tuple(sorted(self._requests.values(), key=lambda item: item.created_at))

    def _expire_locked(self, now: float) -> None:
        changed = False
        for request_id, request in self._requests.items():
            if request.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED} and now >= request.expires_at:
                self._requests[request_id] = replace(request, status=ApprovalStatus.EXPIRED)
                changed = True
        if changed:
            self._persist_locked()

    def _persist_locked(self) -> None:
        if self.snapshot_path is None:
            return
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {**asdict(request), "status": request.status.value}
            for request in sorted(self._requests.values(), key=lambda item: item.created_at)
        ]
        temporary = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.snapshot_path)

    def _load_snapshot(self) -> None:
        """严格恢复审批快照；损坏数据直接失败，不能默认放行。"""

        if self.snapshot_path is None or not self.snapshot_path.exists():
            return
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise TypeError("根节点必须是列表")
            loaded: dict[str, ApprovalRequest] = {}
            for item in payload:
                if not isinstance(item, dict):
                    raise TypeError("审批记录必须是对象")
                request = ApprovalRequest(
                    request_id=str(item["request_id"]),
                    command_sha256=str(item["command_sha256"]),
                    command_preview=str(item.get("command_preview", "[旧版本未保存命令预览]")),
                    reason=str(item["reason"]),
                    status=ApprovalStatus(item["status"]),
                    created_at=float(item["created_at"]),
                    expires_at=float(item["expires_at"]),
                    approver=str(item["approver"]) if item.get("approver") is not None else None,
                    approved_at=float(item["approved_at"]) if item.get("approved_at") is not None else None,
                    consumed_at=float(item["consumed_at"]) if item.get("consumed_at") is not None else None,
                )
                if not request.request_id or not re.fullmatch(r"[0-9a-f]{64}", request.command_sha256):
                    raise ValueError("审批 ID 或命令指纹格式错误")
                if request.request_id in loaded:
                    raise ValueError("审批 ID 重复")
                loaded[request.request_id] = request
            self._requests = loaded
            with self._lock:
                self._expire_locked(self._clock())
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"审批快照无效，已安全拒绝加载：{error}") from error


class PolicyGuardedBashTool(Tool):
    """对 Bash 工具实施风险分级和一次性审批。"""

    def __init__(
        self,
        tool: Tool,
        policy: CommandPolicy,
        *,
        approval_manager: ApprovalManager | None = None,
        allow_review_commands: bool = False,
    ) -> None:
        self._tool = tool
        self._policy = policy
        self._approval_manager = approval_manager
        self._allow_review_commands = allow_review_commands
        self.name = tool.name
        self.description = tool.description
        self.parameters = tool.parameters

    def execute(self, **kwargs) -> str:
        command = str(kwargs.get("command", ""))
        decision = self._policy.evaluate(command)
        if decision.risk is CommandRisk.BLOCKED:
            return f"⚠ Blocked by command policy: {decision.reason}"
        if decision.risk is CommandRisk.REVIEW and not self._allow_review_commands:
            approval = self._approval_manager.consume(command) if self._approval_manager else None
            if approval is None:
                suffix = ""
                if self._approval_manager:
                    request = self._approval_manager.request(command, decision.reason)
                    suffix = f"; request_id={request.request_id}"
                return f"⚠ Approval required by command policy: {decision.reason}{suffix}"
        return self._tool.execute(**kwargs)


_BLOCKED_RULES = (
    (r"\b(?:curl|wget)\b[^\r\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b", "禁止下载内容后直接交给 shell 执行"),
    (r"\b(?:printenv|set|env)\b.*(?:key|token|secret|password)", "禁止读取或筛选敏感环境变量"),
    (r"\b(?:cat|type|more)\b.*(?:\.env|credentials|id_rsa|id_ed25519)", "禁止读取凭据或私钥文件"),
    (r"\bgit\s+push\b.*--force(?:-with-lease)?\b", "禁止强制推送远端分支"),
    (
        r"\b(?:get-content|gc|type)\b.*(?:\.env|credentials|id_rsa|id_ed25519)",
        "禁止通过 PowerShell 读取凭据或私钥文件",
    ),
    (
        r"\bremove-item\b(?=[^\r\n]*-recurse)(?=[^\r\n]*(?:[A-Za-z]:\\|\$env:(?:userprofile|systemroot)))",
        "禁止递归删除磁盘根目录、用户目录或系统目录",
    ),
)

_REVIEW_RULES = (
    (r"\bgit\s+push\b", "推送会改变远端仓库"),
    (r"\bgh\s+pr\s+(?:create|merge|close|reopen|edit)\b", "PR 写操作会改变外部协作状态"),
    (r"\bgh\s+(?:issue|release)\s+(?:create|delete|close|edit)\b", "GitHub 写操作会改变外部状态"),
    (r"\b(?:pip|pip3|uv)\s+install\b|\bpython(?:\.exe)?\s+-m\s+pip\s+install\b", "安装依赖会改变运行环境"),
    (r"\b(?:npm|pnpm|yarn)\s+(?:install|add|remove)\b", "安装依赖会改变运行环境"),
    (r"\b(?:winget|choco|apt(?:-get)?|yum|dnf|brew)\s+install\b", "安装软件会改变主机环境"),
    (r"\b(?:curl|wget)\b", "网络下载需要明确授权"),
    (r"\b(?:invoke-webrequest|invoke-restmethod|iwr|irm)\b", "PowerShell 网络访问需要明确授权"),
    (r"\bstart-process\b", "启动外部进程会改变主机运行状态"),
    (r"\bdocker\s+(?:run|compose\s+up)\b", "启动容器会改变主机运行状态"),
)


class CommandPolicy:
    """按最严重匹配规则对 shell 命令分类。"""

    def evaluate(self, command: str) -> CommandDecision:
        normalized = command.strip()
        for pattern, reason in _BLOCKED_RULES:
            if re.search(pattern, normalized, re.IGNORECASE):
                return CommandDecision(CommandRisk.BLOCKED, reason)
        for pattern, reason in _REVIEW_RULES:
            if re.search(pattern, normalized, re.IGNORECASE):
                return CommandDecision(CommandRisk.REVIEW, reason)
        return CommandDecision(CommandRisk.SAFE, "本地只读或工作区内开发命令")


def _command_digest(command: str) -> str:
    return hashlib.sha256(command.strip().encode("utf-8")).hexdigest()
