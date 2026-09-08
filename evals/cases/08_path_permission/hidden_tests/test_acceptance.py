from permissions import is_path_allowed


def test_similar_prefix_outside_workspace_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    attacker = tmp_path / "workspace-evil" / "secret.txt"
    assert is_path_allowed(str(workspace), str(attacker)) is False


def test_parent_traversal_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert is_path_allowed(str(workspace), str(workspace / ".." / "secret.txt")) is False
