"""让 Agent 按自然语言或代码符号检索仓库相关文件。"""

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from corecoder.repository import RepositoryIndex

from .base import Tool


@dataclass(frozen=True)
class RepositorySearchStats:
    calls: int
    returned_results: int
    context_characters: int
    duration_seconds: float
    returned_paths: tuple[str, ...]


class RepositorySearchTool(Tool):
    name = "repository_search"
    description = (
        "Search a code repository for files and code snippets relevant to a concept, error, "
        "symbol, or feature. Use this before broad file reading when the relevant path is unknown."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Concept, error text, symbol, or feature to find"},
            "path": {"type": "string", "description": "Repository root (default: current directory)"},
            "limit": {"type": "integer", "description": "Maximum ranked results (default: 10, max: 20)"},
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self._returned_results = 0
        self._context_characters = 0
        self._duration_seconds = 0.0
        self._returned_paths: set[str] = set()

    def execute(self, query: str, path: str = ".", limit: int = 10) -> str:
        started = time.perf_counter()
        hits = []
        if not query.strip():
            result = "Error: query cannot be empty"
        else:
            limit = max(1, min(limit, 20))
            try:
                index = RepositoryIndex.build(Path(path))
            except (OSError, ValueError) as error:
                result = f"Error: {error}"
            else:
                hits = index.search(query, limit=limit)
                if not hits:
                    result = "No relevant repository context found."
                else:
                    header = (
                        f"Repository context: {len(hits)} ranked results "
                        f"(indexed {len(index.documents)} files)"
                    )
                    sections = [header]
                    for position, hit in enumerate(hits, 1):
                        reasons = ", ".join(hit.reasons)
                        sections.append(
                            f"\n[{position}] {hit.path}:{hit.line} score={hit.score} "
                            f"({reasons})\n{hit.snippet}"
                        )
                    rendered = "\n".join(sections)
                    result = rendered[:15_000] + (
                        "\n... (context budget reached)" if len(rendered) > 15_000 else ""
                    )

        with self._lock:
            self._calls += 1
            self._returned_results += len(hits)
            self._context_characters += len(result)
            self._duration_seconds += time.perf_counter() - started
            self._returned_paths.update(hit.path for hit in hits)
        return result

    def stats(self) -> RepositorySearchStats:
        with self._lock:
            return RepositorySearchStats(
                calls=self._calls,
                returned_results=self._returned_results,
                context_characters=self._context_characters,
                duration_seconds=self._duration_seconds,
                returned_paths=tuple(sorted(self._returned_paths)),
            )
