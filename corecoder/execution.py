"""命令执行后端：本地执行之外提供资源受限的 Docker 沙箱。"""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerSandboxProfile:
    """可审查的容器资源和隔离配置。"""

    image: str = "corecoder-sandbox:py311"
    memory: str = "512m"
    cpus: float = 1.0
    pids_limit: int = 128
    network_enabled: bool = False

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*", self.image):
            raise ValueError("Docker 镜像名称格式非法")
        if not re.fullmatch(r"[1-9]\d*(?:[kKmMgG])?", self.memory):
            raise ValueError("Docker 内存限制格式非法")
        if self.cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("Docker CPU 和 PID 限制必须大于 0")


class DockerSandboxExecutor:
    """在一次性容器内执行工作区命令，并在超时后清理残留。"""

    def __init__(self, profile: DockerSandboxProfile | None = None) -> None:
        self.profile = profile or DockerSandboxProfile()
        self.profile.validate()

    def execute(self, command: str, *, timeout: int, cwd: str | Path) -> str:
        workspace = Path(cwd).expanduser().resolve()
        if not workspace.is_dir():
            return f"Error: sandbox workspace not found: {workspace}"
        container_name = f"corecoder-{uuid.uuid4().hex[:12]}"
        docker_command = self.build_command(command, workspace, container_name)
        try:
            completed = subprocess.run(
                docker_command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self._force_remove(container_name)
            return f"Error: sandbox timed out after {timeout}s; container cleaned"
        except OSError as error:
            return f"Error: Docker sandbox unavailable: {error}"
        return _render_completed_process(completed)

    def build_command(self, command: str, workspace: Path, container_name: str) -> list[str]:
        profile = self.profile
        network = "bridge" if profile.network_enabled else "none"
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            profile.memory,
            "--cpus",
            str(profile.cpus),
            "--pids-limit",
            str(profile.pids_limit),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--workdir",
            "/workspace",
            profile.image,
            "sh",
            "-lc",
            command,
        ]

    @staticmethod
    def _force_remove(container_name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _render_completed_process(completed: subprocess.CompletedProcess[str]) -> str:
    output = completed.stdout or ""
    if completed.stderr:
        output += ("\n" if output else "") + f"[stderr]\n{completed.stderr}"
    if completed.returncode != 0:
        output += f"\n[exit code: {completed.returncode}]"
    if len(output) > 15_000:
        output = output[:6000] + f"\n\n... truncated ({len(output)} chars total) ...\n\n" + output[-3000:]
    return output.strip() or "(no output)"
