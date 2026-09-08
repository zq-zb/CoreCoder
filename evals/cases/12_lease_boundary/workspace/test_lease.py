from lease import is_lease_expired


def test_before_and_after_expiry():
    assert is_lease_expired(11.0, 10.0) is False
    assert is_lease_expired(9.0, 10.0) is True
