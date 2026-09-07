import re


def redact(text: str) -> str:
    return re.sub(r"api_key=\S+", "api_key=[REDACTED]", text)
