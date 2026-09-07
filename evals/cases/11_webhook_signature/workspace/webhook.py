import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return signature == digest
