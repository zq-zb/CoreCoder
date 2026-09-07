"""本地审批命令行测试。"""

from corecoder.approval_cli import main
from corecoder.security import ApprovalManager, ApprovalStatus


def test_cli_lists_and_approves_persisted_request(tmp_path, capsys):
    snapshot = tmp_path / "approvals.json"
    manager = ApprovalManager(snapshot_path=snapshot)
    request = manager.request("git push origin main", "改变远端")

    assert main(["--store", str(snapshot), "list"]) == 0
    listed = capsys.readouterr().out
    assert request.request_id in listed
    assert "git push origin main" in listed

    assert main([
        "--store",
        str(snapshot),
        "approve",
        request.request_id,
        "--approver",
        "reviewer-cli",
    ]) == 0
    assert "审批完成" in capsys.readouterr().out
    restored = ApprovalManager(snapshot_path=snapshot)
    assert restored.get(request.request_id).status is ApprovalStatus.APPROVED


def test_cli_rejects_corrupted_store(tmp_path, capsys):
    snapshot = tmp_path / "approvals.json"
    snapshot.write_text("not-json", encoding="utf-8")

    assert main(["--store", str(snapshot), "list"]) == 2
    assert "安全拒绝加载" in capsys.readouterr().out
