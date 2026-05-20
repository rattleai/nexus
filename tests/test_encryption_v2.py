"""Tests for AES-256-GCM encryption (v2) and backward compatibility."""

from __future__ import annotations

import pytest


def test_encrypt_produces_v2_format():
    """encrypt() should produce v2:{nonce}:{ciphertext} format."""
    from app.core.encryption import encrypt

    result = encrypt("test-secret")
    assert result.startswith("v2:")
    parts = result.split(":")
    assert len(parts) == 3  # v2, nonce_b64, ciphertext_b64


def test_decrypt_v2_roundtrip():
    """Encrypt then decrypt should return the original plaintext."""
    from app.core.encryption import decrypt, encrypt

    original = "my-super-secret-api-key-12345"
    encrypted = encrypt(original)
    decrypted = decrypt(encrypted)
    assert decrypted == original


def test_decrypt_v1_still_works():
    """v1 (Fernet) ciphertexts should still be decryptable."""
    from cryptography.fernet import Fernet

    from app.core.encryption import _get_key, decrypt

    # Manually create a v1 ciphertext
    key = _get_key(1)
    f = Fernet(key)
    raw_ct = f.encrypt(b"legacy-secret").decode()
    v1_ciphertext = f"v1:{raw_ct}"

    result = decrypt(v1_ciphertext)
    assert result == "legacy-secret"


def test_encrypt_different_nonces():
    """Two encryptions of the same plaintext should produce different ciphertexts."""
    from app.core.encryption import encrypt

    ct1 = encrypt("same-input")
    ct2 = encrypt("same-input")
    assert ct1 != ct2  # Different nonces


def test_decrypt_invalid_v2_raises():
    """Invalid v2 ciphertext should raise ValueError."""
    from app.core.encryption import decrypt

    with pytest.raises(ValueError):
        decrypt("v2:invalid")


def test_decrypt_tampered_ciphertext_raises():
    """Tampered ciphertext should fail authentication."""
    from app.core.encryption import decrypt, encrypt

    encrypted = encrypt("test")
    # Tamper with the ciphertext portion
    parts = encrypted.split(":")
    parts[2] = parts[2][:-4] + "AAAA"
    tampered = ":".join(parts)

    with pytest.raises((ValueError, Exception)):
        decrypt(tampered)
