"""权限结果缓存，不负责策略判断。"""


def policy_cache_key(user_id: str, resource_id: str) -> str:
    return f"access:{user_id}:{resource_id}"
