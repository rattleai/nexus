"""Application-level encryption for sensitive data at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from SECRET_KEY.
This provides authenticated encryption — ciphertext cannot be tampered with.

Usage:
    from app.core.encryption import encrypt, decrypt

    encrypted = encrypt("my-secret-token")
    plaintext = decrypt(encrypted)
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_key() -> bytes:
    """Derive a Fernet-compatible key from SECRET_KEY using SHA256."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext."""
    f = Fernet(_derive_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string.

    Raises ValueError if the ciphertext is invalid or was tampered with.
    """
    f = Fernet(_derive_key())
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt: invalid or corrupted ciphertext") from exc
