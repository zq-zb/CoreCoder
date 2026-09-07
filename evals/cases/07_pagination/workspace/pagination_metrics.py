"""分页监控指标，不参与结果收集。"""


def record_empty_page(items: list[str], next_token: str | None) -> dict:
    return {"items": len(items), "has_next_token": next_token is not None}
