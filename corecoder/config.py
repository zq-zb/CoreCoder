"""Configuration - env vars and defaults."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv():
    """Load .env from cwd, walking up to home dir. No-op if python-dotenv missing."""
    try:
        from dotenv import load_dotenv

        # search cwd first, then parent dirs up to ~
        env_path = Path(".env")
        if not env_path.exists():
            cur = Path.cwd()
            home = Path.home()
            while cur != home and cur != cur.parent:
                candidate = cur / ".env"
                if candidate.exists():
                    env_path = candidate
                    break
                cur = cur.parent
        load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed, silently skip


@dataclass
class Config:
    model: str = "gpt-5.5"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    max_context_tokens: int = 128_000
    provider: str = "openai"

    @classmethod
    def from_env(cls) -> "Config":
        return parse_config()


def parse_config(env=None) -> Config:
    """Build a Config from environment variables, with error handling.

    Malformed values (e.g. ``CORECODER_MAX_TOKENS=abc``) raise a ``ValueError``
    naming the offending variable instead of crashing with a bare traceback.
    """
    # load .env if present (won't override existing env vars)
    _load_dotenv()
    env = env if env is not None else os.environ

    def _get_int(name: str, default: int) -> int:
        raw = env.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"Invalid value for {name}: {raw!r} (expected an integer)") from None
        if value <= 0:
            raise ValueError(f"Invalid value for {name}: {raw!r} (must be positive)")
        return value

    def _get_float(name: str, default: float) -> float:
        raw = env.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"Invalid value for {name}: {raw!r} (expected a number)") from None

    # pick up common api keys automatically
    api_key = env.get("CORECODER_API_KEY") or env.get("OPENAI_API_KEY") or env.get("DEEPSEEK_API_KEY") or ""
    return Config(
        model=env.get("CORECODER_MODEL", "gpt-5.5"),
        api_key=api_key,
        base_url=env.get("OPENAI_BASE_URL") or env.get("CORECODER_BASE_URL"),
        max_tokens=_get_int("CORECODER_MAX_TOKENS", 4096),
        temperature=_get_float("CORECODER_TEMPERATURE", 0.0),
        max_context_tokens=_get_int("CORECODER_MAX_CONTEXT", 128_000),
        provider=env.get("CORECODER_PROVIDER", "openai"),
    )
