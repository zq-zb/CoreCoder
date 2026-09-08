def should_retry(status_code: int, attempt: int, max_attempts: int) -> bool:
    """判断 HTTP 请求是否应该再次执行。"""

    return status_code >= 400 and attempt <= max_attempts
