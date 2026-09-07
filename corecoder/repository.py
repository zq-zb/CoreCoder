"""面向代码仓库的轻量级词法索引与可解释检索。"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".tox"}
_TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java", ".js",
    ".json", ".jsx", ".md", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}
_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}")
_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:async\s+def|def|class|function|interface|type|struct|func)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
_IMPORT_PATTERN = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE)


@dataclass(frozen=True)
class RepositoryDocument:
    path: Path
    relative_path: str
    text: str
    lines: tuple[str, ...]
    terms: Counter[str]
    symbols: frozenset[str]
    references: frozenset[str]


@dataclass(frozen=True)
class RepositorySearchHit:
    path: str
    score: float
    line: int
    reasons: tuple[str, ...]
    snippet: str


class RepositoryIndex:
    """内存索引：适合中小型仓库，结果可解释且不依赖外部服务。"""

    def __init__(self, root: str | Path, documents: list[RepositoryDocument]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.documents = tuple(documents)
        self._postings: dict[str, set[int]] = defaultdict(set)
        self._modules: dict[str, set[int]] = defaultdict(set)
        for index, document in enumerate(self.documents):
            for term in document.terms:
                self._postings[term].add(index)
            self._modules[document.path.stem.lower()].add(index)

    @classmethod
    def build(
        cls,
        root: str | Path,
        *,
        max_files: int = 5000,
        max_file_bytes: int = 512_000,
    ) -> RepositoryIndex:
        base = Path(root).expanduser().resolve()
        if not base.is_dir():
            raise ValueError(f"仓库目录不存在：{root}")

        documents: list[RepositoryDocument] = []
        for path, relative in _iter_repository_files(base):
            if path.suffix.lower() not in _TEXT_SUFFIXES or path.stat().st_size > max_file_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            documents.append(
                RepositoryDocument(
                    path=path,
                    relative_path=relative.as_posix(),
                    text=text,
                    lines=tuple(text.splitlines()),
                    terms=Counter(_tokenize(f"{relative.as_posix()} {text}")),
                    symbols=frozenset(symbol.lower() for symbol in _SYMBOL_PATTERN.findall(text)),
                    references=frozenset(
                        module.split(".")[-1].lower() for module in _IMPORT_PATTERN.findall(text)
                    ),
                )
            )
            if len(documents) >= max_files:
                break
        return cls(base, documents)

    def search(self, query: str, *, limit: int = 10) -> list[RepositorySearchHit]:
        terms = tuple(dict.fromkeys(_tokenize(query)))
        if not terms or limit < 1:
            return []

        candidates: set[int] = set()
        for term in terms:
            candidates.update(self._postings.get(term, ()))

        scores: dict[int, float] = {}
        reasons_by_document: dict[int, list[str]] = defaultdict(list)
        document_count = max(1, len(self.documents))
        for index in candidates:
            document = self.documents[index]
            score = 0.0
            path_lower = document.relative_path.lower()
            for term in terms:
                frequency = document.terms.get(term, 0)
                if not frequency:
                    continue
                document_frequency = len(self._postings[term])
                score += (1 + math.log(frequency)) * math.log(1 + document_count / document_frequency)
                if term in path_lower:
                    score += 6
                    reasons_by_document[index].append(f"路径命中:{term}")
                if term in document.symbols:
                    score += 8
                    reasons_by_document[index].append(f"符号命中:{term}")
            if query.strip().lower() in document.text.lower():
                score += 5
                reasons_by_document[index].append("完整短语命中")
            if document.path.name.lower().startswith(("test_", "tests.")):
                # 测试是重要上下文，但定位根因时生产实现通常应略优先。
                # 只做轻量折扣，不过滤测试文件。
                score *= 0.85
                reasons_by_document[index].append("测试文件轻量降权")
            scores[index] = score

        # 高相关文件显式导入的模块通常属于同一调用链。只传播一跳，避免
        # 依赖图扩散把整个仓库重新塞回候选集合。
        for source_index, source_score in tuple(scores.items()):
            for reference in self.documents[source_index].references:
                for target_index in self._modules.get(reference, ()):
                    if target_index == source_index:
                        continue
                    candidates.add(target_index)
                    # 直接依赖通常比名称相似的旁路模块更接近真实调用链。
                    # 系数通过带干扰文件的基准校准，仍保留词法分作为主体。
                    scores[target_index] = scores.get(target_index, 0.0) + source_score * 0.50
                    reasons_by_document[target_index].append(
                        f"依赖链:{self.documents[source_index].relative_path}"
                    )

        hits: list[RepositorySearchHit] = []
        for index in candidates:
            document = self.documents[index]
            line_number, snippet = _best_snippet(document.lines, terms)
            reasons = reasons_by_document[index]
            hits.append(
                RepositorySearchHit(
                    path=document.relative_path,
                    score=round(scores.get(index, 0.0), 3),
                    line=line_number,
                    reasons=tuple(dict.fromkeys(reasons)) or ("内容词频命中",),
                    snippet=snippet,
                )
            )

        return sorted(hits, key=lambda hit: (-hit.score, hit.path))[:limit]


def repository_fingerprint(
    root: str | Path,
    *,
    max_files: int = 5000,
    max_file_bytes: int = 512_000,
) -> tuple[tuple[str, int, int], ...]:
    """生成轻量仓库指纹，用于判断内存索引是否仍然有效。

    指纹只读取文件元数据，不读取正文。与重新分词整个仓库相比，它适合在
    每次检索前执行；文件路径、大小或修改时间变化都会触发索引重建。
    """

    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"仓库目录不存在：{root}")

    entries: list[tuple[str, int, int]] = []
    for path, relative in _iter_repository_files(base):
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > max_file_bytes:
            continue
        entries.append((relative.as_posix(), stat.st_size, stat.st_mtime_ns))
        if len(entries) >= max_files:
            break
    return tuple(entries)


def _iter_repository_files(base: Path):
    """按稳定顺序遍历文件，并在入口处剪掉依赖和生成目录。"""

    for directory, directory_names, file_names in os.walk(base):
        directory_names[:] = sorted(name for name in directory_names if name not in _SKIP_DIRS)
        for name in sorted(file_names):
            path = Path(directory) / name
            yield path, path.relative_to(base)


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_PATTERN.findall(text)]


def _best_snippet(lines: tuple[str, ...], terms: tuple[str, ...], radius: int = 2) -> tuple[int, str]:
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(lowered.count(term) for term in terms)
        if score > best_score:
            best_index, best_score = index, score
    start = max(0, best_index - radius)
    end = min(len(lines), best_index + radius + 1)
    snippet = "\n".join(f"{line_no + 1}: {lines[line_no]}" for line_no in range(start, end))
    return best_index + 1, snippet
