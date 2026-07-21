import hashlib
import hmac
import secrets
import time


def generate_opaque_token(byte_count: int = 32) -> str:
    return secrets.token_urlsafe(byte_count)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keyed_hash(value: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_signed_csrf_token(signing_key: str) -> str:
    payload = f"{int(time.time())}.{generate_opaque_token(24)}"
    signature = keyed_hash(payload, signing_key)
    return f"{payload}.{signature}"


def verify_signed_csrf_token(token: str, signing_key: str, max_age_seconds: int) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    timestamp, nonce, signature = parts
    if not timestamp.isdigit() or not nonce:
        return False
    expected = keyed_hash(f"{timestamp}.{nonce}", signing_key)
    if not hmac.compare_digest(expected, signature):
        return False
    age = int(time.time()) - int(timestamp)
    return 0 <= age <= max_age_seconds

