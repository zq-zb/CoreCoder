"""资源元数据缓存。"""


def owner_cache_key(resource_id: str) -> str:
    return f"owner:{resource_id}"
