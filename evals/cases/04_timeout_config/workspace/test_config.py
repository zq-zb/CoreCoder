import pytest

from config import parse_timeout


def test_timeout_default_and_string_value():
    assert parse_timeout(None) == 30
    assert parse_timeout("15") == 15


def test_zero_is_rejected():
    with pytest.raises(ValueError):
        parse_timeout("0")
