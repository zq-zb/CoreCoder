import json

import pytest

from corecoder.retrieval_scale_benchmark import run_scale_benchmark, write_scale_benchmark_report


def test_scale_benchmark_measures_each_requested_size() -> None:
    result = run_scale_benchmark((5, 12), repetitions=3)

    assert [point.files for point in result.points] == [5, 12]
    assert all(point.cold_duration_ms > 0 for point in result.points)
    assert all(point.average_warm_duration_ms > 0 for point in result.points)
    assert all(point.single_file_refresh_ms > 0 for point in result.points)


def test_scale_benchmark_validates_inputs() -> None:
    with pytest.raises(ValueError, match="至少为 3"):
        run_scale_benchmark((5,), repetitions=2)
    with pytest.raises(ValueError, match="正整数"):
        run_scale_benchmark((0,), repetitions=3)


def test_scale_benchmark_writes_machine_and_human_reports(tmp_path) -> None:
    result = run_scale_benchmark((5,), repetitions=3)

    json_path, markdown_path = write_scale_benchmark_report(result, tmp_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["points"][0]["files"] == 5
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Warm P95" in markdown
    assert "One-file refresh" in markdown
