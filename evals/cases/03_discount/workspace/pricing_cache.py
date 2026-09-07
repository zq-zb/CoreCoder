"""价格缓存占位模块。"""


def pricing_cache_key(order_id: str) -> str:
    return f"pricing:{order_id}"
