import json

import pytest

from corecoder.retrieval_cache_benchmark import run_cache_benchmark, write_cache_benchmark_report


def test_cache_benchmark_records_cold_and_warm_queries(tmp_path) -> None:
    (tmp_path / "service.py").write_text("def health_check(): return True\n", encoding="utf-8")

    result = run_cache_benchmark(tmp_path, "health_check", repetitions=3)

    assert result.repetitions == 3
    assert result.cache_hits == 2
    assert result.index_builds == 1
    assert result.cold_duration_ms > 0
    assert len(result.warm_durations_ms) == 2


def test_cache_benchmark_rejects_single_run(tmp_path) -> None:
    with pytest.raises(ValueError, match="至少为 2"):
        run_cache_benchmark(tmp_path, "anything", repetitions=1)


def test_cache_benchmark_writes_reports(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text("def health_check(): return True\n", encoding="utf-8")
    result = run_cache_benchmark(repository, "health_check", repetitions=2)

    json_path, markdown_path = write_cache_benchmark_report(result, tmp_path / "reports")

    assert json.loads(json_path.read_text(encoding="utf-8"))["cache_hits"] == 1
    assert "Cold/warm speedup" in markdown_path.read_text(encoding="utf-8")
