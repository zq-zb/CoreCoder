def is_lease_expired(expires_at: float | None, now: float) -> bool:
    if expires_at is None:
        return False
    return expires_at < now
