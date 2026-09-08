from branch_policy import allows_automated_write


def test_normalizes_full_ref_case_and_whitespace():
    assert allows_automated_write(" refs/heads/Main ") is False
    assert allows_automated_write("REFS/HEADS/MASTER") is False


def test_release_is_protected_but_feature_release_is_not():
    assert allows_automated_write("release") is False
    assert allows_automated_write("feature/release-notes") is True
