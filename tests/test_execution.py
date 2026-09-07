"""Docker 沙箱命令构造、资源限制和超时清理测试。"""

import subprocess
from pathlib import Path

from corecoder.execution import DockerSandboxExecutor, DockerSandboxProfile
from corecoder.tools.bash import BashTool


def test_docker_command_contains_isolation_and_resource_limits(tmp_path):
    profile = DockerSandboxProfile(memory="256m", cpus=0.5, pids_limit=64)
    executor = DockerSandboxExecutor(profile)

    command = executor.build_command("python -m pytest -q", tmp_path, "corecoder-test")

    assert command[:2] == ["docker", "run"]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in command
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--pids-limit") + 1] == "64"
    assert command[-3:] == ["sh", "-lc", "python -m pytest -q"]


def test_docker_executor_renders_output(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="2 passed\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DockerSandboxExecutor().execute("pytest", timeout=10, cwd=tmp_path)

    assert result == "2 passed"


def test_timeout_forces_container_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DockerSandboxExecutor().execute("sleep 100", timeout=1, cwd=tmp_path)

    assert "container cleaned" in result
    assert calls[1][:3] == ["docker", "rm", "-f"]
    assert calls[1][-1] in calls[0]


def test_bash_tool_can_use_sandbox_executor(tmp_path):
    class FakeExecutor:
        def execute(self, command: str, *, timeout: int, cwd: str | Path) -> str:
            return f"sandbox:{command}:{timeout}:{Path(cwd).name}"

    result = BashTool(executor=FakeExecutor()).execute(command="echo safe", timeout=9)

    assert result.startswith("sandbox:echo safe:9:")


def test_invalid_sandbox_profile_is_rejected():
    try:
        DockerSandboxExecutor(DockerSandboxProfile(image="bad image; rm -rf /"))
    except ValueError as error:
        assert "镜像名称" in str(error)
    else:
        raise AssertionError("非法镜像名称必须被拒绝")
