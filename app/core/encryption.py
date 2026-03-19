"""Versioned envelope encryption for sensitive data at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with keys derived from source secrets
via HKDF (HMAC-based Key Derivation Function, RFC 5869). Supports key
versioning for seamless rotation — new data is always encrypted with the
latest key, but old data can still be decrypted with previous versions.

Envelope encryption pattern:
    - Each key version derives a unique Fernet key via HKDF
    - Ciphertext is prefixed with version tag: "v{N}:{ciphertext}"
    - Decryption tries the tagged version first, then falls back to all known versions

Usage:
    from app.core.encryption import encrypt, decrypt

    encrypted = encrypt("my-secret-token")     # Uses latest key version
    plaintext = decrypt(encrypted)             # Auto-detects version
"""

import base64
import functools
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

# Current key version — bump when rotating ENCRYPTION_KEY or upgrading cipher
# v1: Fernet (AES-128-CBC + HMAC-SHA256)
# v2: AES-256-GCM (authenticated encryption with 12-byte nonce)
_CURRENT_KEY_VERSION = 2

# Version tag prefix
_VERSION_PREFIX = "v"


def _derive_key_from_source(source_key: str, version: int = 1) -> bytes:
    """Derive a Fernet-compatible key using HKDF with version-specific info.

    Each version uses a different `info` parameter for domain separation,
    ensuring key independence between versions.
    """
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,  # acceptable when source key has high entropy
        info=f"saas-platform-encryption-v{version}".encode(),
    )
    derived = hkdf.derive(source_key.encode())
    return base64.urlsafe_b64encode(derived)


@functools.lru_cache(maxsize=8)
def _get_key(version: int) -> bytes:
    """Get the encryption key for a specific version.

    Version 1 uses the primary ENCRYPTION_KEY (or SECRET_KEY fallback).
    Additional versions can be configured via ENCRYPTION_KEY_V{N} settings.
    """
    if version == 1:
        source_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    else:
        # Support additional key versions via environment variables
        attr = f"ENCRYPTION_KEY_V{version}"
        source_key = getattr(settings, attr, "") or settings.ENCRYPTION_KEY or settings.SECRET_KEY
    return _derive_key_from_source(source_key, version)


@functools.lru_cache(maxsize=8)
def _get_aes_gcm_key(version: int) -> bytes:
    """Get a raw 32-byte AES-256 key for a specific version.

    Uses a different HKDF info parameter than Fernet keys for domain
    separation, ensuring key independence between cipher modes.
    """
    if version == 2:
        source_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    else:
        attr = f"ENCRYPTION_KEY_V{version}"
        source_key = getattr(settings, attr, "") or settings.ENCRYPTION_KEY or settings.SECRET_KEY

    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=f"saas-platform-aes256gcm-v{version}".encode(),
    )
    return hkdf.derive(source_key.encode())


def _get_all_key_versions() -> list[int]:
    """Return all known key versions in descending order (current first)."""
    return list(range(_CURRENT_KEY_VERSION, 0, -1))


def _parse_version_tag(ciphertext: str) -> tuple[int | None, str]:
    """Parse version tag from ciphertext.

    Returns (version, raw_ciphertext). If no tag, returns (None, ciphertext).
    """
    if ciphertext.startswith(_VERSION_PREFIX) and ":" in ciphertext[:10]:
        tag, _, raw = ciphertext.partition(":")
        try:
            version = int(tag[len(_VERSION_PREFIX):])
            return version, raw
        except ValueError:
            pass
    return None, ciphertext


def encrypt(plaintext: str) -> str:
    """Encrypt a string with the current key version.

    v1: Fernet (AES-128-CBC + HMAC-SHA256) → "v1:{fernet_token}"
    v2: AES-256-GCM → "v2:{nonce_b64}:{ciphertext_b64}"
    """
    if _CURRENT_KEY_VERSION >= 2:
        return _encrypt_v2(plaintext)
    key = _get_key(_CURRENT_KEY_VERSION)
    f = Fernet(key)
    raw = f.encrypt(plaintext.encode()).decode()
    return f"{_VERSION_PREFIX}{_CURRENT_KEY_VERSION}:{raw}"


def _encrypt_v2(plaintext: str) -> str:
    """Encrypt using AES-256-GCM with 12-byte random nonce."""
    key = _get_aes_gcm_key(_CURRENT_KEY_VERSION)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    nonce_b64 = base64.urlsafe_b64encode(nonce).decode()
    ct_b64 = base64.urlsafe_b64encode(ciphertext).decode()
    return f"{_VERSION_PREFIX}{_CURRENT_KEY_VERSION}:{nonce_b64}:{ct_b64}"


def decrypt(ciphertext: str) -> str:
    """Decrypt a versioned ciphertext string.

    Dispatches to the appropriate decryption method based on version tag:
    - v2+: AES-256-GCM
    - v1/untagged: Fernet

    Raises ValueError if the ciphertext is invalid or no key can decrypt it.
    """
    version, raw = _parse_version_tag(ciphertext)

    # Try the tagged version first
    if version is not None:
        if version >= 2:
            try:
                return _decrypt_v2(raw, version)
            except Exception:
                pass
        else:
            try:
                f = Fernet(_get_key(version))
                return f.decrypt(raw.encode()).decode()
            except InvalidToken:
                pass

    # Fallback: try all known versions (for untagged legacy data)
    for v in _get_all_key_versions():
        if v == version:
            continue  # Already tried above
        if v >= 2:
            continue  # v2+ always has a tag; untagged data is always v1
        try:
            f = Fernet(_get_key(v))
            return f.decrypt(raw.encode()).decode()
        except InvalidToken:
            continue

    raise ValueError("Failed to decrypt: invalid ciphertext or no matching key version")


def _decrypt_v2(raw: str, version: int) -> str:
    """Decrypt AES-256-GCM ciphertext: "{nonce_b64}:{ciphertext_b64}"."""
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Invalid v2 ciphertext format")
    nonce = base64.urlsafe_b64decode(parts[0])
    ct = base64.urlsafe_b64decode(parts[1])
    key = _get_aes_gcm_key(version)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()
