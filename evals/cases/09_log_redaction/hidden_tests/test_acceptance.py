from redaction import redact


def test_multiple_secret_types_and_case_are_hidden():
    value = "TOKEN=abc password=123 Authorization=Bearer-secret"
    result = redact(value)
    assert "abc" not in result
    assert "123" not in result
    assert "Bearer-secret" not in result
    assert result.count("[REDACTED]") == 3
