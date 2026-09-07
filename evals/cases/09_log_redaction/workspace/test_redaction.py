from redaction import redact


def test_api_key_is_hidden():
    assert redact("api_key=secret") == "api_key=[REDACTED]"


def test_normal_text_is_unchanged():
    assert redact("status=healthy") == "status=healthy"
