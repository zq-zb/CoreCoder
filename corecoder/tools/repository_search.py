"""让 Agent 按自然语言或代码符号检索仓库相关文件。"""

from pathlib import Path

from corecoder.repository import RepositoryIndex

from .base import Tool


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

    def execute(self, query: str, path: str = ".", limit: int = 10) -> str:
        if not query.strip():
            return "Error: query cannot be empty"
        limit = max(1, min(limit, 20))
        try:
            index = RepositoryIndex.build(Path(path))
        except (OSError, ValueError) as error:
            return f"Error: {error}"

        hits = index.search(query, limit=limit)
        if not hits:
            return "No relevant repository context found."

        sections = [f"Repository context: {len(hits)} ranked results (indexed {len(index.documents)} files)"]
        for position, hit in enumerate(hits, 1):
            reasons = ", ".join(hit.reasons)
            sections.append(
                f"\n[{position}] {hit.path}:{hit.line} score={hit.score} ({reasons})\n{hit.snippet}"
            )
        result = "\n".join(sections)
        return result[:15_000] + ("\n... (context budget reached)" if len(result) > 15_000 else "")
