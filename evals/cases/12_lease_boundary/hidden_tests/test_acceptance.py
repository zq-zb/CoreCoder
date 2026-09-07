from lease import is_lease_expired


def test_equal_timestamp_is_expired():
    assert is_lease_expired(10.0, 10.0) is True


def test_missing_expiry_is_not_expired():
    assert is_lease_expired(None, 10.0) is False
