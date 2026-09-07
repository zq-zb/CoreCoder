from pathlib import Path


def is_path_allowed(workspace: str, candidate: str) -> bool:
    root = Path(workspace).resolve()
    path = Path(candidate).resolve()
    return str(path).startswith(str(root))
