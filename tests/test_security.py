"""Tests for password hashing and JWT token utilities."""

from datetime import timedelta

import jwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "my-secure-password"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_different_hashes_for_same_password(self):
        """bcrypt should produce different hashes each time (unique salt)."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token({"sub": "user-123", "tenant_id": "t-456"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "t-456"
        assert payload["type"] == "access"

    def test_expired_token_raises(self):
        token = create_access_token({"sub": "user-123"}, expires_delta=timedelta(seconds=-1))
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_invalid_token_raises(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token("not-a-valid-token")

    def test_wrong_type_raises(self):
        """A token without type=access should be rejected."""
        import jwt as pyjwt

        from app.core.security import _get_effective_algorithm, _get_jwt_signing_key

        token = pyjwt.encode(
            {"sub": "user-123", "type": "refresh", "iss": "saas-platform", "aud": "saas-platform"},
            _get_jwt_signing_key(),
            algorithm=_get_effective_algorithm(),
        )
        with pytest.raises(jwt.InvalidTokenError, match="Not an access token"):
            decode_access_token(token)


class TestRefreshToken:
    def test_create_returns_raw_and_hash(self):
        raw, hashed = create_refresh_token()
        assert len(raw) > 20
        assert len(hashed) == 64  # SHA-256 hex digest
        assert raw != hashed

    def test_uniqueness(self):
        raw1, hash1 = create_refresh_token()
        raw2, hash2 = create_refresh_token()
        assert raw1 != raw2
        assert hash1 != hash2
