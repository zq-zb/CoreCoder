from gateway import authorize_resource


def test_owner_can_access_own_resource():
    assert authorize_resource("user-1", "user", "user-1") is True


def test_non_owner_is_denied():
    assert authorize_resource("user-1", "user", "user-2") is False


def test_admin_can_access_other_users_resource():
    assert authorize_resource("admin-1", "admin", "user-2") is True


def test_unknown_role_does_not_bypass_owner_check():
    assert authorize_resource("service-1", "unknown", "service-1") is True
