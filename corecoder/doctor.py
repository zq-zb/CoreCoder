"""CoreCoder 本地运行环境诊断，不访问外部网络或输出凭据。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from .config import Config
from .security import ApprovalManager


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True)
class DiagnosticReport:
    healthy: bool
    checks: tuple[DiagnosticCheck, ...]


def run_diagnostics(workspace: str | Path = ".") -> DiagnosticReport:
    """执行只涉及本机状态的快速诊断。"""

    root = Path(workspace).expanduser().resolve()
    checks = [
        _python_check(),
        _dependency_check("openai"),
        _dependency_check("mcp"),
        _command_check("git"),
        _command_check("gh", required=False),
        _command_check("docker", required=False),
        _docker_engine_check(),
        _workspace_check(root),
        _config_check(),
        _approval_store_check(root / ".corecoder" / "approvals.json"),
    ]
    return DiagnosticReport(
        healthy=all(check.status is not CheckStatus.FAIL for check in checks),
        checks=tuple(checks),
    )


def _python_check() -> DiagnosticCheck:
    version = ".".join(str(part) for part in sys.version_info[:3])
    status = CheckStatus.PASS if sys.version_info >= (3, 10) else CheckStatus.FAIL
    return DiagnosticCheck("python", status, f"Python {version}（要求 >= 3.10）")


def _dependency_check(module: str) -> DiagnosticCheck:
    available = importlib.util.find_spec(module) is not None
    return DiagnosticCheck(
        f"dependency:{module}",
        CheckStatus.PASS if available else CheckStatus.FAIL,
        "已安装" if available else "未安装",
    )


def _command_check(command: str, *, required: bool = True) -> DiagnosticCheck:
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        available = completed.returncode == 0
        message = (completed.stdout or completed.stderr).splitlines()[0][:200] if available else "命令不可用"
    except (OSError, subprocess.SubprocessError):
        available = False
        message = "命令不可用"
    status = CheckStatus.PASS if available else (CheckStatus.FAIL if required else CheckStatus.WARN)
    return DiagnosticCheck(f"command:{command}", status, message)


def _workspace_check(root: Path) -> DiagnosticCheck:
    if not root.is_dir():
        return DiagnosticCheck("workspace", CheckStatus.FAIL, f"目录不存在：{root}")
    try:
        with tempfile.NamedTemporaryFile(prefix=".corecoder-doctor-", dir=root, delete=True):
            pass
    except OSError as error:
        return DiagnosticCheck("workspace", CheckStatus.FAIL, f"目录不可写：{error}")
    return DiagnosticCheck("workspace", CheckStatus.PASS, f"目录存在且可写：{root}")


def _docker_engine_check() -> DiagnosticCheck:
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return DiagnosticCheck("docker-engine", CheckStatus.WARN, "Docker Engine 不可访问，沙箱模式不可用")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Docker Engine 不可访问").splitlines()[-1][:200]
        return DiagnosticCheck("docker-engine", CheckStatus.WARN, detail)
    return DiagnosticCheck("docker-engine", CheckStatus.PASS, f"Docker Engine {completed.stdout.strip()} 可访问")


def _config_check() -> DiagnosticCheck:
    try:
        config = Config.from_env()
    except ValueError as error:
        return DiagnosticCheck("model-config", CheckStatus.FAIL, str(error))
    if not config.api_key:
        return DiagnosticCheck("model-config", CheckStatus.WARN, f"模型 {config.model}，未配置 API Key")
    return DiagnosticCheck(
        "model-config",
        CheckStatus.PASS,
        f"模型 {config.model}，Provider {config.provider}，API Key 已配置（内容不显示）",
    )


def _approval_store_check(path: Path) -> DiagnosticCheck:
    if not path.exists():
        return DiagnosticCheck("approval-store", CheckStatus.PASS, "尚未创建审批文件")
    try:
        requests = ApprovalManager(snapshot_path=path).list_requests()
    except ValueError as error:
        return DiagnosticCheck("approval-store", CheckStatus.FAIL, str(error))
    return DiagnosticCheck("approval-store", CheckStatus.PASS, f"审批文件有效，共 {len(requests)} 条记录")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查 CoreCoder 本地运行环境")
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", dest="as_json")
    options = parser.parse_args(argv)
    report = run_diagnostics(options.workspace)
    if options.as_json:
        payload = {
            "healthy": report.healthy,
            "checks": [{**asdict(check), "status": check.status.value} for check in report.checks],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for check in report.checks:
            print(f"[{check.status.value.upper():4}] {check.name}: {check.message}")
        print("\n总体状态：" + ("健康" if report.healthy else "异常"))
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
