"""Coding Agent 的任务状态、测试反馈和结果报告。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .agent import Agent
from .prompt import system_prompt
from .security import ApprovalManager, CommandPolicy, PolicyGuardedBashTool
from .tools.base import Tool


class CodingTaskState(str, Enum):
    """对外可观察的 Coding Agent 任务阶段。"""

    ANALYZING = "analyzing"
    EDITING = "editing"
    TESTING = "testing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class CodingTaskEvent:
    """一次工具执行对任务状态产生的结构化记录。"""

    state: CodingTaskState
    tool_name: str
    summary: str


@dataclass(frozen=True)
class TestRun:
    """一次被 Coding Agent 识别为测试的命令结果。"""

    command: str
    passed: bool
    output: str


@dataclass(frozen=True)
class CodingTaskReport:
    """Coding Agent 任务结束后产生的可复查报告。"""

    state: CodingTaskState
    final_response: str
    changed_files: tuple[str, ...]
    test_runs: tuple[TestRun, ...]
    events: tuple[CodingTaskEvent, ...]
    verified: bool
    failure_reason: str | None = None


class CodingTaskLimitError(RuntimeError):
    """测试失败次数超过允许的自动修复上限。"""


class CodingTaskVerified(RuntimeError):
    """修改后的测试已经通过，由状态机正常结束工具循环。"""


_EDIT_TOOLS = {"edit_file", "write_file"}
_TEST_PATTERN = re.compile(
    r"(?:\s-m\s+(?:pytest|unittest)(?:\s|$)|(?:^|\s)(?:pytest|unittest|npm\s+test|"
    r"npm\s+run\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test)(?:\s|$))",
    re.IGNORECASE,
)
_FAILED_RESULT_PATTERN = re.compile(r"\[exit code:\s*[1-9]\d*\]|Error: timed out", re.IGNORECASE)
_PATH_ARGUMENTS = {
    "read_file": "file_path",
    "write_file": "file_path",
    "edit_file": "file_path",
    "glob": "path",
    "grep": "path",
    "repository_search": "path",
}


class _WorkspaceGuardedTool(Tool):
    """在真实文件工具前增加工作区路径边界。"""

    def __init__(self, tool: Tool, workspace: Path, path_argument: str) -> None:
        self._tool = tool
        self._workspace = workspace
        self._path_argument = path_argument
        self.name = tool.name
        self.description = tool.description
        self.parameters = tool.parameters

    def execute(self, **kwargs) -> str:
        guarded = dict(kwargs)
        raw_path = guarded.get(self._path_argument, ".")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self._workspace)
        except ValueError:
            return f"Error: path outside coding workspace: {raw_path}"
        guarded[self._path_argument] = str(resolved)
        return self._tool.execute(**guarded)


@dataclass
class _TaskTracker:
    workspace: Path
    max_fix_attempts: int
    stop_after_verified: bool = False
    state: CodingTaskState = CodingTaskState.ANALYZING
    changed_files: set[str] = field(default_factory=set)
    test_runs: list[TestRun] = field(default_factory=list)
    events: list[CodingTaskEvent] = field(default_factory=list)
    revision: int = 0
    verified_revision: int | None = None
    failed_tests: int = 0
    policy_denials: list[str] = field(default_factory=list)

    def tool_started(self, name: str, arguments: dict) -> None:
        if name == "bash" and _is_test_command(str(arguments.get("command", ""))):
            self.state = CodingTaskState.TESTING

    def tool_finished(self, name: str, arguments: dict, result: str) -> str | None:
        if result.startswith(("⚠ Blocked", "⚠ Approval required")):
            self.policy_denials.append(_first_line(result))
            self.events.append(CodingTaskEvent(CodingTaskState.FAILED, name, _first_line(result)))
            self.state = CodingTaskState.FAILED
            return

        if name in _EDIT_TOOLS and not result.startswith("Error:"):
            self.revision += 1
            self.verified_revision = None
            self.state = CodingTaskState.FIXING if self.failed_tests else CodingTaskState.EDITING
            file_path = arguments.get("file_path")
            if file_path:
                self.changed_files.add(str(Path(file_path).expanduser().resolve()))
            self.events.append(CodingTaskEvent(self.state, name, _first_line(result)))
            return

        if name == "bash" and _is_test_command(str(arguments.get("command", ""))):
            passed = _FAILED_RESULT_PATTERN.search(result) is None
            self.test_runs.append(TestRun(str(arguments["command"]), passed, result))
            if passed:
                self.verified_revision = self.revision
                self.state = CodingTaskState.TESTING
            else:
                self.failed_tests += 1
                self.state = CodingTaskState.FIXING
            self.events.append(CodingTaskEvent(self.state, name, "测试通过" if passed else "测试失败"))
            if passed and self.stop_after_verified and self.revision > 0:
                raise CodingTaskVerified("最后一次代码修改已通过测试")
            if passed and self.revision > 0:
                return (
                    "检测到最后一次代码修改后的相关测试已经通过。若任务要求均已满足，"
                    "请立即返回最终总结，不要重复读取、重写或再次运行同一测试。"
                )
            if self.failed_tests > self.max_fix_attempts:
                raise CodingTaskLimitError(
                    f"测试已失败 {self.failed_tests} 次，超过最大自动修复次数 "
                    f"{self.max_fix_attempts}"
                )
        return None


class CodingTaskRunner:
    """复用 Agent Loop，将代码修改、测试和修复整理成一次任务。"""

    def __init__(
        self,
        agent: Agent,
        workspace: str | Path,
        max_fix_attempts: int = 3,
        *,
        command_policy: CommandPolicy | None = None,
        allow_review_commands: bool = False,
        approval_manager: ApprovalManager | None = None,
        require_changes: bool = False,
        stop_after_verified: bool = False,
    ) -> None:
        if max_fix_attempts < 0:
            raise ValueError("最大自动修复次数不能小于 0")
        self.agent = agent
        self.workspace = Path(workspace).expanduser().resolve()
        self.max_fix_attempts = max_fix_attempts
        self.command_policy = command_policy or CommandPolicy()
        self.allow_review_commands = allow_review_commands
        self.approval_manager = approval_manager
        self.require_changes = require_changes
        self.stop_after_verified = stop_after_verified
        self._install_workspace_guards()

    def run(self, task: str, on_token=None, on_tool=None) -> CodingTaskReport:
        tracker = _TaskTracker(
            self.workspace,
            self.max_fix_attempts,
            stop_after_verified=self.stop_after_verified,
        )

        def started(name: str, arguments: dict) -> None:
            tracker.tool_started(name, arguments)
            if on_tool:
                on_tool(name, arguments)

        def finished(name: str, arguments: dict, result: str) -> str | None:
            return tracker.tool_finished(name, arguments, result)

        failure_reason = None
        try:
            final_response = self.agent.chat(
                self._task_prompt(task),
                on_token=on_token,
                on_tool=started,
                on_tool_result=finished,
            )
        except CodingTaskVerified:
            final_response = "代码修改已通过相关测试，状态机已按验收条件结束任务。"
        except CodingTaskLimitError as error:
            final_response = str(error)
            failure_reason = str(error)

        reached_round_limit = final_response in {
            "(reached maximum tool-call rounds)",
            "(model returned empty response twice)",
        }
        has_current_verification = tracker.verified_revision == tracker.revision and bool(tracker.test_runs)
        verified = has_current_verification
        if tracker.policy_denials:
            state = CodingTaskState.FAILED
            failure_reason = tracker.policy_denials[-1]
        elif failure_reason or reached_round_limit:
            state = CodingTaskState.FAILED
            failure_reason = failure_reason or (
                "模型连续返回空响应" if "empty response" in final_response else "达到 Agent 最大工具调用轮数"
            )
        elif self.require_changes and not tracker.changed_files:
            state = CodingTaskState.FAILED
            failure_reason = "任务要求修改代码，但未检测到文件变更"
        elif tracker.changed_files and not verified:
            state = CodingTaskState.FAILED
            failure_reason = "最后一次代码修改后没有通过测试"
        else:
            state = CodingTaskState.COMPLETED

        return CodingTaskReport(
            state=state,
            final_response=final_response,
            changed_files=tuple(sorted(tracker.changed_files)),
            test_runs=tuple(tracker.test_runs),
            events=tuple(tracker.events),
            verified=verified,
            failure_reason=failure_reason,
        )

    def _task_prompt(self, task: str) -> str:
        repair_contract = ""
        if self.require_changes:
            repair_contract = (
                "这是一个已经确认存在缺陷的修复任务，不能以‘无需修改’结束。"
                f"工具交互轮次上限为 {self.agent.max_rounds}，请优先读取任务指定的实现文件和可见测试，"
                "理解后尽早修改，并为修改后的测试保留预算；不要反复读取相同文件或重复运行已通过的测试。"
            )
        return (
            f"工作区：{self.workspace}\n"
            f"任务：{task}\n\n"
            f"{repair_contract}"
            "请完成编码闭环：先搜索并读取相关代码，再做最小必要修改，"
            "然后运行相关测试。如果测试失败，根据真实错误继续修复并重新测试。"
            "不要在没有验证最后一次修改时宣布完成。最后一次修改通过相关测试后，"
            "如果任务要求已经满足，请立即返回简短总结，不要重复读取、重写或再次运行已通过的测试。"
        )

    def _install_workspace_guards(self) -> None:
        """只限制会读写路径的工具，不改变其公开 Schema。"""

        guarded_tools: list[Tool] = []
        for tool in self.agent.tools:
            path_argument = _PATH_ARGUMENTS.get(tool.name)
            if path_argument and not isinstance(tool, _WorkspaceGuardedTool):
                tool = _WorkspaceGuardedTool(tool, self.workspace, path_argument)
            elif tool.name == "bash" and not isinstance(tool, PolicyGuardedBashTool):
                tool = PolicyGuardedBashTool(
                    tool,
                    self.command_policy,
                    allow_review_commands=self.allow_review_commands,
                    approval_manager=self.approval_manager,
                )
            guarded_tools.append(tool)
        self.agent.tools = guarded_tools
        self.agent._tool_by_name = {tool.name: tool for tool in guarded_tools}
        self.agent._system = system_prompt(guarded_tools)


def _is_test_command(command: str) -> bool:
    return _TEST_PATTERN.search(command) is not None


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""
