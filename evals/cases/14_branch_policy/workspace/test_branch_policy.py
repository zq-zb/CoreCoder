from branch_policy import allows_automated_write


def test_direct_main_is_blocked_and_feature_is_allowed():
    assert allows_automated_write("main") is False
    assert allows_automated_write("feature/fix-ci") is True
