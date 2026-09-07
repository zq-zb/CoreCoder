from gateway import authorize_resource


def test_admin_can_access_any_resource():
    assert authorize_resource("admin-1", "admin", "user-2") is True


def test_user_cannot_access_someone_elses_resource():
    assert authorize_resource("user-1", "user", "user-2") is False
