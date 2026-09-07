from webhook import verify_signature


def test_rejects_unrelated_signature():
    assert verify_signature(b"payload", "not-a-signature", "secret") is False
