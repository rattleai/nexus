"""Application-level encryption for sensitive data at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from SECRET_KEY
via HKDF (HMAC-based Key Derivation Function, RFC 5869). HKDF is the
gold-standard approach for deriving cryptographic keys from a master secret —
it provides proper domain separation and is resistant to related-key attacks,
unlike plain SHA-256 hashing.

Usage:
    from app.core.encryption import encrypt, decrypt

    encrypted = encrypt("my-secret-token")
    plaintext = decrypt(encrypted)
"""

import base64
import functools

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


@functools.lru_cache(maxsize=1)
def _derive_key() -> bytes:
    """Derive a Fernet-compatible key using HKDF.

    Uses ENCRYPTION_KEY if set (recommended), falling back to SECRET_KEY for
    backward compatibility. A dedicated ENCRYPTION_KEY allows rotating JWT
    signing keys (SECRET_KEY) without breaking encrypted data at rest.

    HKDF (RFC 5869) is the recommended approach for extracting a
    cryptographic key from a shared secret. The `info` parameter provides
    domain separation so the same source key can safely derive independent
    keys for different purposes.
    """
    source_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,  # acceptable when source key has high entropy
        info=b"saas-platform-encryption-v1",
    )
    derived = hkdf.derive(source_key.encode())
    return base64.urlsafe_b64encode(derived)


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
