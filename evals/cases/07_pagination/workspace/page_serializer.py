"""页面序列化辅助模块。"""


def serialize_page(items: list[str], next_token: str | None) -> dict:
    return {"items": items, "next_token": next_token}
