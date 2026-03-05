"""Password hashing and JWT token utilities.

Uses passlib+bcrypt for password hashing and PyJWT for token management.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt.

    Pre-hashes with SHA-256 to handle passwords >72 bytes (bcrypt truncation limit).
    """
    sha_digest = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return pwd_context.hash(sha_digest)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its hash."""
    sha_digest = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return pwd_context.verify(sha_digest, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token with jti, iss, and aud claims."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iss": "saas-platform",
        "aud": "saas-platform",
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or signature is invalid.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer="saas-platform",
        audience="saas-platform",
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def create_refresh_token() -> tuple[str, str]:
    """Create a refresh token.

    Returns:
        Tuple of (raw_token, token_hash). Store the hash in DB, send the raw token to client.
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash
