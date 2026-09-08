"""权限审计记录，不参与放行决策。"""


def record_access_decision(user_id: str, allowed: bool) -> dict:
    return {"user_id": user_id, "allowed": allowed}
