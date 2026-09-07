"""生成可在 Windows 与 POSIX Shell 中执行的工作目录命令。"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path


def command_in_directory(
    directory: str | Path,
    arguments: Sequence[str | Path],
    *,
    windows: bool | None = None,
) -> str:
    """把参数安全引用为一条先进入目录、再执行程序的 Shell 命令。"""

    if not arguments:
        raise ValueError("命令参数不能为空")

    use_windows = os.name == "nt" if windows is None else windows
    # 不在这里 resolve/重写路径；调用方可能在 Windows 上测试 POSIX 命令，反之亦然。
    directory_text = str(directory)
    argument_text = [str(argument) for argument in arguments]

    if use_windows:
        quoted_directory = subprocess.list2cmdline([directory_text])
        quoted_command = subprocess.list2cmdline(argument_text)
        return f"cd /d {quoted_directory} && {quoted_command}"

    return f"cd {shlex.quote(directory_text)} && {shlex.join(argument_text)}"
