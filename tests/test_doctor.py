"""本地运行环境诊断测试。"""

import json

from corecoder.doctor import CheckStatus, main, run_diagnostics


def test_diagnostics_report_contains_operational_checks(tmp_path):
    report = run_diagnostics(tmp_path)
    names = {check.name for check in report.checks}

    assert "python" in names
    assert "dependency:mcp" in names
    assert "command:git" in names
    assert "command:gh" in names
    assert "docker-engine" in names
    assert "workspace" in names
    assert "model-config" in names
    assert "approval-store" in names


def test_corrupted_approval_store_makes_report_unhealthy(tmp_path):
    runtime_dir = tmp_path / ".corecoder"
    runtime_dir.mkdir()
    (runtime_dir / "approvals.json").write_text("broken", encoding="utf-8")

    report = run_diagnostics(tmp_path)
    approval = next(check for check in report.checks if check.name == "approval-store")

    assert approval.status is CheckStatus.FAIL
    assert report.healthy is False


def test_json_output_never_contains_api_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CORECODER_API_KEY", "doctor-super-secret")

    exit_code = main(["--workspace", str(tmp_path), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code in {0, 1}
    assert "doctor-super-secret" not in output
    assert isinstance(payload["checks"], list)
