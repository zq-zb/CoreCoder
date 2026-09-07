"""缓存分页 token，不决定是否继续抓取。"""


def cache_next_token(next_token: str | None) -> str:
    return next_token or "finished"
