import hashlib
import hmac


def hash_api_key(raw_key: str) -> str:
    """Hash an API key with HMAC-SHA256 for storage.

    Uses a static pepper so that a leaked database cannot be brute-forced
    with precomputed rainbow tables against raw SHA-256.
    """
    from app.config import settings

    pepper = (settings.SECRET_KEY or "default-pepper").encode()
    return hmac.new(pepper, raw_key.encode(), hashlib.sha256).hexdigest()
