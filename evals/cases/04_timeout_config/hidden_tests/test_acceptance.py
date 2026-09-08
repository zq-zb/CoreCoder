import pytest

from config import parse_timeout


def test_timeout_contract():
    assert parse_timeout(None) == 30
    assert parse_timeout("1") == 1
    with pytest.raises(ValueError):
        parse_timeout("0")
    with pytest.raises(ValueError):
        parse_timeout("-5")
    with pytest.raises(ValueError):
        parse_timeout("abc")
