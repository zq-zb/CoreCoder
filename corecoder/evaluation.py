"""Coding Agent 的可复现任务评测、隐藏验收和指标汇总。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .agent import Agent
from .coding_task import CodingTaskReport, CodingTaskRunner, CodingTaskState


class EvaluationFailure(str, Enum):
    """评测失败原因，用于判断应该改 Agent 的哪一层。"""

    AGENT_FAILED = "agent_failed"
    HIDDEN_TEST_FAILED = "hidden_test_failed"
    UNEXPECTED_FILE_CHANGE = "unexpected_file_change"
    TOOL_BUDGET_EXCEEDED = "tool_budget_exceeded"
    VERIFICATION_ERROR = "verification_error"


@dataclass(frozen=True)
class VerificationSpec:
    """独立于 Agent 的验收命令；参数列表执行，不经过 shell。"""

    command: tuple[str, ...]
    timeout: float = 30.0


@dataclass(frozen=True)
class EvaluationCase:
    """一个可重复运行的 Coding Agent 任务。"""

    case_id: str
    task: str
    case_dir: Path
    workspace_dir: Path
    verification: VerificationSpec
    allowed_changed_files: tuple[str, ...]
    relevant_context_files: tuple[str, ...] = ()
    max_tool_calls: int = 20
    max_fix_attempts: int = 3
    tags: tuple[str, ...] = ()

    @classmethod
    def load(cls, manifest_path: str | Path) -> EvaluationCase:
        manifest = Path(manifest_path).resolve()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        case_dir = manifest.parent
        workspace_dir = (case_dir / data.get("workspace", "workspace")).resolve()
        verification_data = data["verification"]
        case = cls(
            case_id=str(data["id"]),
            task=str(data["task"]),
            case_dir=case_dir,
            workspace_dir=workspace_dir,
            verification=VerificationSpec(
                command=tuple(str(value) for value in verification_data["command"]),
                timeout=float(verification_data.get("timeout", 30.0)),
            ),
            allowed_changed_files=tuple(_normalize_relative_path(value) for value in data["allowed_changed_files"]),
            relevant_context_files=tuple(
                _normalize_relative_path(value) for value in data.get("relevant_context_files", [])
            ),
            max_tool_calls=int(data.get("max_tool_calls", 20)),
            max_fix_attempts=int(data.get("max_fix_attempts", 3)),
            tags=tuple(str(value) for value in data.get("tags", [])),
        )
        case.validate()
        return case

    def validate(self) -> None:
        if not self.case_id or not self.task:
            raise ValueError("评测案例 id 和 task 不能为空")
        if not self.workspace_dir.is_dir():
            raise ValueError(f"评测工作区不存在：{self.workspace_dir}")
        if not self.verification.command or self.verification.timeout <= 0:
            raise ValueError("验收命令不能为空，且超时时间必须大于 0")
        if self.max_tool_calls <= 0 or self.max_fix_attempts < 0:
            raise ValueError("工具调用上限必须大于 0，修复次数不能小于 0")
        missing_context = [
            path for path in self.relevant_context_files if not (self.workspace_dir / path).is_file()
        ]
        if missing_context:
            raise ValueError(f"相关上下文文件不存在：{', '.join(missing_context)}")


@dataclass(frozen=True)
class VerificationResult:
    """隐藏验收命令的真实运行结果。"""

    passed: bool
    exit_code: int | None
    duration_seconds: float
    output: str
    timed_out: bool = False


@dataclass(frozen=True)
class EvaluationResult:
    """单个案例的评测结果和可解释失败原因。"""

    case_id: str
    success: bool
    failures: tuple[EvaluationFailure, ...]
    task_state: str
    task_failure_reason: str | None
    task_events: tuple[str, ...]
    tool_trace: tuple[str, ...]
    hidden_tests_passed: bool
    scope_compliant: bool
    tool_budget_compliant: bool
    changed_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    tool_calls: int
    failed_test_runs: int
    duration_seconds: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float | None
    context_compressions: int
    context_tokens_saved: int
    repository_search_calls: int
    repository_search_results: int
    repository_context_characters: int
    repository_search_duration_seconds: float
    repository_target_recall: float | None
    repository_context_recall: float | None
    verification: VerificationResult
    agent_response: str


@dataclass(frozen=True)
class EvaluationSummary:
    """多个案例的聚合指标。"""

    total_cases: int
    passed_cases: int
    success_rate: float
    hidden_test_pass_rate: float
    scope_compliance_rate: float
    average_tool_calls: float
    average_failed_test_runs: float
    average_duration_seconds: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_estimated_cost: float | None
    total_context_compressions: int
    total_context_tokens_saved: int
    total_repository_search_calls: int
    average_repository_search_results: float
    total_repository_context_characters: int
    average_repository_search_duration_seconds: float
    average_repository_target_recall: float | None
    average_repository_context_recall: float | None


@dataclass(frozen=True)
class CaseStability:
    """同一案例重复运行后的稳定通过比例。"""

    case_id: str
    runs: int
    passes: int
    pass_rate: float


@dataclass(frozen=True)
class EvaluationMetadata:
    """确保两次评测成绩可以被公平比较的实验元数据。"""

    created_at_utc: str
    model: str
    provider: str
    strategy: str
    dataset_fingerprint: str
    python_version: str
    git_commit: str | None


AgentFactory = Callable[[EvaluationCase, Path], Agent]


class CodingAgentEvaluator:
    """在隔离副本中运行 Agent，并由外部验收器独立评分。"""

    def __init__(self, agent_factory: AgentFactory, *, keep_workspaces: bool = False) -> None:
        self.agent_factory = agent_factory
        self.keep_workspaces = keep_workspaces

    def run_case(self, case: EvaluationCase) -> EvaluationResult:
        case.validate()
        run_root = Path(tempfile.mkdtemp(prefix=f"corecoder-eval-{case.case_id}-"))
        workspace = run_root / "workspace"
        shutil.copytree(case.workspace_dir, workspace)
        before = _snapshot_files(workspace)
        started = time.perf_counter()
        try:
            agent = self.agent_factory(case, workspace)
        except Exception as error:
            verification = self._verify(case, workspace, run_root)
            result = EvaluationResult(
                case_id=case.case_id,
                success=False,
                failures=(EvaluationFailure.AGENT_FAILED,),
                task_state=CodingTaskState.FAILED.value,
                task_failure_reason=str(error),
                task_events=(),
                tool_trace=(),
                hidden_tests_passed=verification.passed,
                scope_compliant=True,
                tool_budget_compliant=True,
                changed_files=(),
                unexpected_files=(),
                tool_calls=0,
                failed_test_runs=0,
                duration_seconds=time.perf_counter() - started,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost=None,
                context_compressions=0,
                context_tokens_saved=0,
                repository_search_calls=0,
                repository_search_results=0,
                repository_context_characters=0,
                repository_search_duration_seconds=0.0,
                repository_target_recall=None,
                repository_context_recall=None,
                verification=verification,
                agent_response=f"Agent 初始化失败：{error}",
            )
            if not self.keep_workspaces:
                shutil.rmtree(run_root, ignore_errors=True)
            return result
        prompt_before = int(getattr(agent.llm, "total_prompt_tokens", 0) or 0)
        completion_before = int(getattr(agent.llm, "total_completion_tokens", 0) or 0)
        cost_before = _estimated_cost(agent)
        message_start = len(agent.messages)

        try:
            task_report = CodingTaskRunner(
                agent,
                workspace,
                max_fix_attempts=case.max_fix_attempts,
                require_changes=True,
            ).run(case.task)
        except Exception as error:
            task_report = CodingTaskReport(
                state=CodingTaskState.FAILED,
                final_response=f"评测中 Agent 异常：{error}",
                changed_files=(),
                test_runs=(),
                events=(),
                verified=False,
                failure_reason=str(error),
            )

        verification = self._verify(case, workspace, run_root)
        after = _snapshot_files(workspace)
        changed_files = tuple(sorted(_changed_paths(before, after)))
        allowed = set(case.allowed_changed_files)
        unexpected = tuple(path for path in changed_files if path not in allowed)
        tool_calls = _count_tool_calls(agent.messages[message_start:])
        scope_compliant = not unexpected
        tool_budget_compliant = tool_calls <= case.max_tool_calls
        failures: list[EvaluationFailure] = []
        if task_report.state is not CodingTaskState.COMPLETED:
            failures.append(EvaluationFailure.AGENT_FAILED)
        if not verification.passed:
            failures.append(
                EvaluationFailure.VERIFICATION_ERROR
                if verification.exit_code is None
                else EvaluationFailure.HIDDEN_TEST_FAILED
            )
        if not scope_compliant:
            failures.append(EvaluationFailure.UNEXPECTED_FILE_CHANGE)
        if not tool_budget_compliant:
            failures.append(EvaluationFailure.TOOL_BUDGET_EXCEEDED)

        prompt_tokens = int(getattr(agent.llm, "total_prompt_tokens", 0) or 0) - prompt_before
        completion_tokens = int(getattr(agent.llm, "total_completion_tokens", 0) or 0) - completion_before
        cost_after = _estimated_cost(agent)
        estimated_cost = None if cost_before is None or cost_after is None else max(0.0, cost_after - cost_before)
        context_stats = agent.context.stats()
        repository_metrics = _repository_metrics(
            agent,
            case.allowed_changed_files,
            case.relevant_context_files,
        )
        result = EvaluationResult(
            case_id=case.case_id,
            success=not failures,
            failures=tuple(failures),
            task_state=task_report.state.value,
            task_failure_reason=task_report.failure_reason,
            task_events=tuple(
                f"{event.state.value}:{event.tool_name}:{event.summary}" for event in task_report.events
            ),
            tool_trace=_tool_trace(agent.messages[message_start:]),
            hidden_tests_passed=verification.passed,
            scope_compliant=scope_compliant,
            tool_budget_compliant=tool_budget_compliant,
            changed_files=changed_files,
            unexpected_files=unexpected,
            tool_calls=tool_calls,
            failed_test_runs=sum(not run.passed for run in task_report.test_runs),
            duration_seconds=time.perf_counter() - started,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost=estimated_cost,
            context_compressions=context_stats.compression_count,
            context_tokens_saved=context_stats.tokens_saved,
            repository_search_calls=repository_metrics[0],
            repository_search_results=repository_metrics[1],
            repository_context_characters=repository_metrics[2],
            repository_search_duration_seconds=repository_metrics[3],
            repository_target_recall=repository_metrics[4],
            repository_context_recall=repository_metrics[5],
            verification=verification,
            agent_response=task_report.final_response,
        )
        if not self.keep_workspaces:
            shutil.rmtree(run_root, ignore_errors=True)
        return result

    def run_suite(self, cases: Iterable[EvaluationCase]) -> tuple[list[EvaluationResult], EvaluationSummary]:
        results = [self.run_case(case) for case in cases]
        return results, summarize_results(results)

    @staticmethod
    def _verify(case: EvaluationCase, workspace: Path, run_root: Path) -> VerificationResult:
        replacements = {
            "{python}": sys.executable,
            "{workspace}": str(workspace),
            "{case_dir}": str(case.case_dir),
            "{run_root}": str(run_root),
        }
        command = [
            _replace_placeholders(part, replacements)
            for part in case.verification.command
        ]
        environment = os.environ.copy()
        current_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(workspace) + (os.pathsep + current_python_path if current_python_path else "")
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=case.verification.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            return VerificationResult(
                passed=False,
                exit_code=None,
                duration_seconds=time.perf_counter() - started,
                output=_truncate_output(str(error)),
                timed_out=timed_out,
            )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return VerificationResult(
            passed=completed.returncode == 0,
            exit_code=completed.returncode,
            duration_seconds=time.perf_counter() - started,
            output=_truncate_output(output.strip()),
        )


def discover_cases(root: str | Path) -> list[EvaluationCase]:
    """按稳定顺序加载数据集，保证多次评测可比较。"""

    return [EvaluationCase.load(path) for path in sorted(Path(root).glob("*/case.json"))]


def summarize_results(results: list[EvaluationResult]) -> EvaluationSummary:
    total = len(results)
    if total == 0:
        return EvaluationSummary(
            total_cases=0, passed_cases=0, success_rate=0.0, hidden_test_pass_rate=0.0,
            scope_compliance_rate=0.0, average_tool_calls=0.0, average_failed_test_runs=0.0,
            average_duration_seconds=0.0, total_prompt_tokens=0, total_completion_tokens=0,
            total_estimated_cost=0.0, total_context_compressions=0, total_context_tokens_saved=0,
            total_repository_search_calls=0, average_repository_search_results=0.0,
            total_repository_context_characters=0,
            average_repository_search_duration_seconds=0.0, average_repository_target_recall=None,
            average_repository_context_recall=None,
        )
    costs = [result.estimated_cost for result in results]
    total_cost = None if any(cost is None for cost in costs) else sum(cost or 0.0 for cost in costs)
    return EvaluationSummary(
        total_cases=total,
        passed_cases=sum(result.success for result in results),
        success_rate=sum(result.success for result in results) / total,
        hidden_test_pass_rate=sum(result.hidden_tests_passed for result in results) / total,
        scope_compliance_rate=sum(result.scope_compliant for result in results) / total,
        average_tool_calls=sum(result.tool_calls for result in results) / total,
        average_failed_test_runs=sum(result.failed_test_runs for result in results) / total,
        average_duration_seconds=sum(result.duration_seconds for result in results) / total,
        total_prompt_tokens=sum(result.prompt_tokens for result in results),
        total_completion_tokens=sum(result.completion_tokens for result in results),
        total_estimated_cost=total_cost,
        total_context_compressions=sum(result.context_compressions for result in results),
        total_context_tokens_saved=sum(result.context_tokens_saved for result in results),
        total_repository_search_calls=sum(result.repository_search_calls for result in results),
        average_repository_search_results=sum(result.repository_search_results for result in results) / total,
        total_repository_context_characters=sum(result.repository_context_characters for result in results),
        average_repository_search_duration_seconds=(
            sum(result.repository_search_duration_seconds for result in results) / total
        ),
        average_repository_target_recall=_average_optional(
            [result.repository_target_recall for result in results]
        ),
        average_repository_context_recall=_average_optional(
            [result.repository_context_recall for result in results]
        ),
    )


def summarize_stability(results: list[EvaluationResult]) -> tuple[CaseStability, ...]:
    """按案例聚合重复运行结果，避免用单次成功代表稳定成功。"""

    grouped: dict[str, list[bool]] = {}
    for result in results:
        grouped.setdefault(result.case_id, []).append(result.success)
    return tuple(
        CaseStability(
            case_id=case_id,
            runs=len(outcomes),
            passes=sum(outcomes),
            pass_rate=sum(outcomes) / len(outcomes),
        )
        for case_id, outcomes in sorted(grouped.items())
    )


def write_evaluation_report(
    results: list[EvaluationResult],
    summary: EvaluationSummary,
    output_dir: str | Path,
    metadata: EvaluationMetadata | None = None,
) -> tuple[Path, Path]:
    """同时生成便于程序比较的 JSON 和便于面试展示的 Markdown。"""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "evaluation.json"
    markdown_path = destination / "evaluation.md"
    payload = {
        "metadata": _jsonable(asdict(metadata)) if metadata else None,
        "summary": _jsonable(asdict(summary)),
        "results": [_jsonable(asdict(result)) for result in results],
        "stability": [_jsonable(asdict(item)) for item in summarize_stability(results)],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CoreCoder Evaluation Report",
        "",
    ]
    if metadata:
        lines.extend([
            f"- Model: {metadata.model}",
            f"- Provider: {metadata.provider}",
            f"- Strategy: {metadata.strategy}",
            f"- Dataset: `{metadata.dataset_fingerprint}`",
            f"- Git commit: `{metadata.git_commit or 'dirty/unavailable'}`",
            "",
        ])
    lines.extend([
        f"- Cases: {summary.passed_cases}/{summary.total_cases}",
        f"- Success rate: {summary.success_rate:.1%}",
        f"- Hidden test pass rate: {summary.hidden_test_pass_rate:.1%}",
        f"- Scope compliance rate: {summary.scope_compliance_rate:.1%}",
        f"- Average tool calls: {summary.average_tool_calls:.2f}",
        f"- Average failed test runs: {summary.average_failed_test_runs:.2f}",
        f"- Average duration: {summary.average_duration_seconds:.2f}s",
        f"- Context compressions: {summary.total_context_compressions}",
        f"- Estimated context tokens saved: {summary.total_context_tokens_saved}",
        f"- Repository search calls: {summary.total_repository_search_calls}",
        f"- Repository context characters: {summary.total_repository_context_characters}",
        f"- Average repository search duration: {summary.average_repository_search_duration_seconds:.4f}s",
        f"- Average repository target recall: {_format_optional_rate(summary.average_repository_target_recall)}",
        f"- Average repository context recall: {_format_optional_rate(summary.average_repository_context_recall)}",
        "",
        "| Case | Success | Hidden tests | Scope | Tool calls | Repo searches | Target recall | Context recall | Failures | Task reason |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for result in results:
        failure_text = ", ".join(failure.value for failure in result.failures) or "-"
        lines.append(
            f"| {result.case_id} | {'yes' if result.success else 'no'} | "
            f"{'pass' if result.hidden_tests_passed else 'fail'} | "
            f"{'pass' if result.scope_compliant else 'fail'} | {result.tool_calls} | "
            f"{result.repository_search_calls} | {_format_optional_rate(result.repository_target_recall)} | "
            f"{_format_optional_rate(result.repository_context_recall)} | "
            f"{failure_text} | "
            f"{(result.task_failure_reason or '-').replace('|', '/')} |"
        )
    stability = summarize_stability(results)
    if any(item.runs > 1 for item in stability):
        lines.extend(["", "## Stability", "", "| Case | Passes | Runs | Pass rate |", "|---|---:|---:|---:|"])
        for item in stability:
            lines.append(f"| {item.case_id} | {item.passes} | {item.runs} | {item.pass_rate:.1%} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def build_evaluation_metadata(
    cases: Iterable[EvaluationCase],
    *,
    model: str,
    provider: str,
    strategy: str,
    repository: str | Path = ".",
) -> EvaluationMetadata:
    """根据案例内容和运行环境生成可复现实验标识。"""

    case_list = list(cases)
    digest = hashlib.sha256()
    for case in sorted(case_list, key=lambda item: item.case_id):
        for path in sorted(case.case_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(case.case_dir).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
    return EvaluationMetadata(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        model=model,
        provider=provider,
        strategy=strategy,
        dataset_fingerprint=digest.hexdigest()[:16],
        python_version=sys.version.split()[0],
        git_commit=_git_commit(Path(repository)),
    )


def _snapshot_files(workspace: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache", ".git"} for part in path.parts):
            continue
        relative = path.relative_to(workspace).as_posix()
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def _count_tool_calls(messages: list[dict]) -> int:
    return sum(len(message.get("tool_calls", [])) for message in messages if message.get("role") == "assistant")


def _tool_trace(messages: list[dict]) -> tuple[str, ...]:
    """只记录工具名，不保存参数或文件内容，兼顾诊断价值与报告体积。"""

    return tuple(
        str(call.get("function", {}).get("name", "unknown"))
        for message in messages
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    )


def _normalize_relative_path(value: Any) -> str:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"允许修改的文件必须是工作区内相对路径：{value}")
    return path.as_posix()


def _replace_placeholders(value: str, replacements: dict[str, str]) -> str:
    for marker, replacement in replacements.items():
        value = value.replace(marker, replacement)
    return value


def _estimated_cost(agent: Agent) -> float | None:
    try:
        return agent.llm.estimated_cost
    except (AttributeError, TypeError):
        return None


def _repository_metrics(
    agent: Agent,
    target_files: tuple[str, ...],
    context_files: tuple[str, ...],
) -> tuple[int, int, int, float, float | None, float | None]:
    """从可能被工作区守卫包装的检索工具中提取稳定指标。"""

    for candidate in agent.tools:
        tool = candidate
        while hasattr(tool, "_tool"):
            tool = tool._tool
        if getattr(tool, "name", None) != "repository_search" or not hasattr(tool, "stats"):
            continue
        stats = tool.stats()
        if stats.calls == 0:
            return 0, 0, 0, 0.0, None, None
        targets = set(target_files)
        contexts = set(context_files)
        target_recall = len(targets.intersection(stats.returned_paths)) / len(targets) if targets else None
        context_recall = (
            len(contexts.intersection(stats.returned_paths)) / len(contexts) if contexts else None
        )
        return (
            stats.calls,
            stats.returned_results,
            stats.context_characters,
            stats.duration_seconds,
            target_recall,
            context_recall,
        )
    return 0, 0, 0, 0.0, None, None


def _average_optional(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _format_optional_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _truncate_output(output: str, limit: int = 12_000) -> str:
    if len(output) <= limit:
        return output
    return output[:limit] + "\n... verification output truncated ..."


def _git_commit(repository: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def result_to_dict(result: EvaluationResult) -> dict[str, Any]:
    """为外部系统提供稳定的可 JSON 序列化结果。"""

    return _jsonable(asdict(result))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
