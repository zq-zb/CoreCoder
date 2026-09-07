def extract_failures(logs: str, limit: int = 20) -> list[str]:
    return [line for line in logs.splitlines() if "ERROR" in line][:limit]
