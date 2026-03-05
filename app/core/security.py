"""Password hashing and JWT token utilities.

Uses passlib+argon2id for password hashing and PyJWT for token management.
Argon2id is the recommended KDF (OWASP, RFC 9106) — resistant to both
GPU/ASIC attacks and side-channel attacks, with no 72-byte truncation issue.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.config import settings

# argon2id primary, bcrypt as deprecated fallback for existing hashes.
# passlib auto-flags bcrypt hashes as needing rehash.
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], default="argon2", deprecated=["bcrypt"])


def hash_password(plain: str) -> str:
    """Hash a plaintext password using argon2id."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its hash.

    Supports both argon2id (current) and bcrypt (legacy) hashes.
    Legacy bcrypt hashes used a SHA-256 pre-hash, so we try both forms.
    """
    # Try direct verification first (argon2id or plain bcrypt)
    if pwd_context.verify(plain, hashed):
        return True
    # Fallback: legacy bcrypt hashes were created with SHA-256 pre-hashing
    if hashed.startswith("$2b$"):
        sha_digest = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return pwd_context.verify(sha_digest, hashed)
    return False


def needs_rehash(hashed: str) -> bool:
    """Return True if the hash should be upgraded (e.g. bcrypt → argon2id)."""
    return pwd_context.needs_update(hashed)


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
