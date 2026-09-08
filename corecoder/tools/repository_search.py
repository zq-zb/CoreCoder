"""让 Agent 按自然语言或代码符号检索仓库相关文件。"""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from corecoder.repository import RepositoryFingerprint, RepositoryIndex, repository_fingerprint

from .base import Tool


@dataclass(frozen=True)
class RepositorySearchStats:
    calls: int
    returned_results: int
    context_characters: int
    duration_seconds: float
    returned_paths: tuple[str, ...]
    cache_hits: int
    index_builds: int
    cache_invalidations: int
    incremental_refreshes: int


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
        self._cache_lock = threading.Lock()
        self._calls = 0
        self._returned_results = 0
        self._context_characters = 0
        self._duration_seconds = 0.0
        self._returned_paths: set[str] = set()
        self._cache_hits = 0
        self._index_builds = 0
        self._cache_invalidations = 0
        self._incremental_refreshes = 0
        # Agent 级小型 LRU：避免不同 Agent 共享工作区状态，同时限制内存占用。
        self._index_cache: OrderedDict[
            Path, tuple[RepositoryFingerprint, RepositoryIndex]
        ] = OrderedDict()
        self._max_cached_repositories = 4

    def _get_index(self, path: str) -> RepositoryIndex:
        root = Path(path).expanduser().resolve()
        # 指纹比较和重建在同一把锁内完成，避免并发查询重复构建索引。
        with self._cache_lock:
            fingerprint = repository_fingerprint(root)
            cached = self._index_cache.get(root)
            if cached is not None and cached[0] == fingerprint:
                self._index_cache.move_to_end(root)
                self._cache_hits += 1
                return cached[1]

            if cached is not None:
                self._cache_invalidations += 1
                index = cached[1].refresh(cached[0], fingerprint)
                self._incremental_refreshes += 1
            else:
                index = RepositoryIndex.build(root)
                self._index_builds += 1
            self._index_cache[root] = (fingerprint, index)
            self._index_cache.move_to_end(root)
            while len(self._index_cache) > self._max_cached_repositories:
                self._index_cache.popitem(last=False)
            return index

    def execute(self, query: str, path: str = ".", limit: int = 10) -> str:
        started = time.perf_counter()
        hits = []
        if not query.strip():
            result = "Error: query cannot be empty"
        else:
            limit = max(1, min(limit, 20))
            try:
                index = self._get_index(path)
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
        # 同时保护调用统计和缓存统计，避免监控线程读到跨时刻的组合值。
        with self._cache_lock, self._lock:
            return RepositorySearchStats(
                calls=self._calls,
                returned_results=self._returned_results,
                context_characters=self._context_characters,
                duration_seconds=self._duration_seconds,
                returned_paths=tuple(sorted(self._returned_paths)),
                cache_hits=self._cache_hits,
                index_builds=self._index_builds,
                cache_invalidations=self._cache_invalidations,
                incremental_refreshes=self._incremental_refreshes,
            )
