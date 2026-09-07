from corecoder.repository import RepositoryIndex
from corecoder.tools import get_tool


def test_repository_search_ranks_path_and_symbol_matches(tmp_path) -> None:
    (tmp_path / "payments").mkdir()
    (tmp_path / "payments" / "retry_policy.py").write_text(
        "def calculate_backoff(attempt):\n    return attempt * 2\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.md").write_text(
        "The retry policy should use exponential backoff.\n",
        encoding="utf-8",
    )

    hits = RepositoryIndex.build(tmp_path).search("calculate_backoff retry policy")

    assert hits[0].path == "payments/retry_policy.py"
    assert "符号命中:calculate_backoff" in hits[0].reasons
    assert "def calculate_backoff" in hits[0].snippet


def test_repository_index_skips_generated_and_large_files(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret.py").write_text("def hidden(): pass", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"retry policy")
    (tmp_path / "large.py").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "app.py").write_text("def retry_request(): pass", encoding="utf-8")

    index = RepositoryIndex.build(tmp_path, max_file_bytes=50)

    assert [document.relative_path for document in index.documents] == ["app.py"]


def test_repository_search_tool_returns_bounded_explainable_context(tmp_path) -> None:
    (tmp_path / "auth.py").write_text(
        "def verify_webhook_signature(payload, signature):\n    return False\n",
        encoding="utf-8",
    )
    tool = get_tool("repository_search")

    result = tool.execute("verify_webhook_signature", str(tmp_path), limit=50)

    assert "Repository context:" in result
    assert "auth.py:1" in result
    assert "符号命中:verify_webhook_signature" in result
    assert len(result) <= 15_030
    stats = tool.stats()
    assert stats.calls == 1
    assert stats.returned_results == 1
    assert stats.context_characters == len(result)
    assert stats.duration_seconds > 0
    assert stats.returned_paths == ("auth.py",)


def test_repository_search_handles_empty_and_missing_inputs(tmp_path) -> None:
    tool = get_tool("repository_search")

    assert tool.execute("  ", str(tmp_path)) == "Error: query cannot be empty"
    assert tool.execute("anything", str(tmp_path / "missing")).startswith("Error:")


def test_repository_search_returns_no_match_without_dumping_repository(tmp_path) -> None:
    (tmp_path / "app.py").write_text("def start(): pass", encoding="utf-8")

    result = get_tool("repository_search").execute("nonexistent_symbol", str(tmp_path))

    assert result == "No relevant repository context found."
