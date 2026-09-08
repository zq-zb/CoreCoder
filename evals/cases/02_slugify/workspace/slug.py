def slugify(value: str) -> str:
    """Convert words separated by whitespace to a lowercase slug."""

    return value.lower().replace(" ", "-")
