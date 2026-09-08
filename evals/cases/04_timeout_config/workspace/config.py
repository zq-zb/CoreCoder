def parse_timeout(value: str | None) -> int:
    """Parse a positive timeout, using 30 seconds when omitted."""

    if value is None:
        return 30
    return int(value)
