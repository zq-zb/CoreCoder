import hashlib
import hmac

from webhook import verify_signature


def test_accepts_github_sha256_signature():
    payload = b'{"action":"opened"}'
    digest = hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, f"sha256={digest}", "secret") is True


def test_rejects_missing_prefix_and_bad_hex():
    digest = hmac.new(b"secret", b"payload", hashlib.sha256).hexdigest()
    assert verify_signature(b"payload", digest, "secret") is False
    assert verify_signature(b"payload", "sha256=xyz", "secret") is False
