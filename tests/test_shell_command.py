from pathlib import Path

import pytest

from corecoder.shell_command import command_in_directory


def test_command_in_directory_builds_windows_command() -> None:
    command = command_in_directory(
        Path("C:/workspace with spaces"),
        ["C:/Python/python.exe", "-m", "pytest", "test demo.py"],
        windows=True,
    )

    assert command.startswith('cd /d "C:\\workspace with spaces" && ')
    assert '"test demo.py"' in command


def test_command_in_directory_builds_posix_command() -> None:
    command = command_in_directory(
        "/tmp/workspace with spaces",
        ["/usr/bin/python", "-m", "pytest", "test demo.py"],
        windows=False,
    )

    assert command == "cd '/tmp/workspace with spaces' && /usr/bin/python -m pytest 'test demo.py'"


def test_command_in_directory_rejects_empty_arguments() -> None:
    with pytest.raises(ValueError, match="命令参数不能为空"):
        command_in_directory(".", [])
