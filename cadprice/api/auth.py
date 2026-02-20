import hashlib


def hash_api_key(raw_key: str) -> str:
    """Hash an API key with SHA-256 for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
