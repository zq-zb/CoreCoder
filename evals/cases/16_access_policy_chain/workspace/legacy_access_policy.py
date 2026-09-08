"""旧版权限逻辑，已停止被网关引用。"""


def can_access_legacy(role: str) -> bool:
    return role in {"admin", "operator"}
