from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    items: list[str]
    next_token: str | None
