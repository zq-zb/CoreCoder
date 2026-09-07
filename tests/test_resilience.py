"""离线故障演练报告测试。"""

import json

from corecoder.resilience import main, run_resilience_campaign, write_resilience_report


def test_resilience_campaign_passes_all_fault_scenarios():
    report = run_resilience_campaign()

    assert report.total_scenarios == 5
    assert report.passed_scenarios == 5
    assert report.pass_rate == 1.0
    assert {scenario.name for scenario in report.scenarios} == {
        "worker_loss_requeue",
        "retry_exhaustion",
        "cancel_during_worker_loss",
        "idempotency_storm",
        "approval_replay",
    }
    assert all(scenario.recovery_ms >= 0 for scenario in report.scenarios)


def test_resilience_report_contains_evidence(tmp_path):
    report = run_resilience_campaign()

    json_path, markdown_path = write_resilience_report(report, tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["pass_rate"] == 1.0
    assert payload["scenarios"][0]["evidence"]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Recovery" in markdown
    assert "## Evidence" in markdown


def test_resilience_cli_writes_report(tmp_path, capsys):
    assert main(["--output", str(tmp_path)]) == 0
    assert "5/5" in capsys.readouterr().out
    assert (tmp_path / "resilience-campaign.json").exists()
