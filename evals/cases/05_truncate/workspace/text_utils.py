def truncate(text: str, limit: int) -> str:
    """Return text no longer than limit, adding an ellipsis when truncated."""

    if len(text) <= limit:
        return text
    return text[:limit] + "..."
