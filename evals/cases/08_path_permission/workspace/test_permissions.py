from permissions import is_path_allowed


def test_child_path_is_allowed(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert is_path_allowed(str(workspace), str(workspace / "src" / "app.py")) is True
