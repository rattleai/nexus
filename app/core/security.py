"""Password hashing and JWT token utilities.

Uses passlib+argon2id for password hashing and PyJWT for token management.
Argon2id is the recommended KDF (OWASP, RFC 9106) — resistant to both
GPU/ASIC attacks and side-channel attacks, with no 72-byte truncation issue.

Supports RS256 (asymmetric) JWT signing for production multi-service
architectures, with HS256 fallback for development.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import structlog
from passlib.context import CryptContext

from app.config import settings

logger = structlog.stdlib.get_logger()

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
    """Return True if the hash should be upgraded (e.g. bcrypt -> argon2id)."""
    return pwd_context.needs_update(hashed)


def _get_jwt_signing_key() -> str | bytes:
    """Return the JWT signing key based on the configured algorithm."""
    if settings.JWT_ALGORITHM in ("RS256", "ES256") and settings.JWT_PRIVATE_KEY:
        return settings.JWT_PRIVATE_KEY.replace("\\n", "\n")
    return settings.SECRET_KEY


def _get_jwt_verification_key() -> str | bytes:
    """Return the JWT verification key based on the configured algorithm."""
    if settings.JWT_ALGORITHM in ("RS256", "ES256") and settings.JWT_PUBLIC_KEY:
        return settings.JWT_PUBLIC_KEY.replace("\\n", "\n")
    return settings.SECRET_KEY


def _get_effective_algorithm() -> str:
    """Return the effective JWT algorithm (falls back to HS256 if keys not configured)."""
    if settings.JWT_ALGORITHM in ("RS256", "ES256"):
        if settings.JWT_PRIVATE_KEY and settings.JWT_PUBLIC_KEY:
            return settings.JWT_ALGORITHM
        return "HS256"
    return settings.JWT_ALGORITHM


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token with jti, iss, and aud claims."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    jti = uuid.uuid4().hex
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
        "jti": jti,
        "iss": "saas-platform",
        "aud": "saas-platform",
    })
    algorithm = _get_effective_algorithm()
    return jwt.encode(to_encode, _get_jwt_signing_key(), algorithm=algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or signature is invalid.
    """
    algorithm = _get_effective_algorithm()
    payload = jwt.decode(
        token,
        _get_jwt_verification_key(),
        algorithms=[algorithm],
        issuer="saas-platform",
        audience="saas-platform",
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


async def is_token_revoked(jti: str) -> bool:
    """Check if a JWT access token has been revoked via Redis blacklist."""
    try:
        from app.core.redis import redis_pool
        result = await redis_pool.get(f"jwt:revoked:{jti}")
        return result is not None
    except Exception:
        # Redis unavailable — fail CLOSED to prevent use of revoked tokens.
        # This means all JWT auth fails during Redis outage, but prevents
        # a revoked token from being accepted. Prefer safety over availability.
        logger.error("token_revocation_check_failed_closing", jti=jti)
        return True


async def revoke_access_token(jti: str, ttl_seconds: int | None = None) -> None:
    """Add a JWT access token to the revocation blacklist.

    The blacklist entry expires when the token would naturally expire,
    preventing unbounded Redis memory growth.
    """
    if not jti:
        return
    try:
        from app.core.redis import redis_pool
        ttl = ttl_seconds or (settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        await redis_pool.setex(f"jwt:revoked:{jti}", ttl, "1")
    except Exception:
        logger.warning("token_revocation_failed", jti=jti)


async def revoke_all_user_tokens(user_id: str) -> None:
    """Mark all access tokens for a user as revoked by setting a 'revoked since' timestamp.

    Any token issued before this timestamp will be rejected.
    """
    try:
        from app.core.redis import redis_pool
        ttl = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        await redis_pool.setex(f"jwt:user_revoked:{user_id}", ttl, str(int(datetime.now(UTC).timestamp())))
    except Exception:
        logger.warning("user_token_revocation_failed", user_id=user_id)


async def is_user_token_revoked(user_id: str, issued_at: int) -> bool:
    """Check if a user's tokens issued before a certain time have been revoked."""
    try:
        from app.core.redis import redis_pool
        revoked_since = await redis_pool.get(f"jwt:user_revoked:{user_id}")
        if revoked_since and issued_at < int(revoked_since):
            return True
        return False
    except Exception:
        return False


def get_jwks_public_key() -> dict | None:
    """Return the public key in JWK format for the /.well-known/jwks.json endpoint."""
    if _get_effective_algorithm() not in ("RS256", "ES256") or not settings.JWT_PUBLIC_KEY:
        return None

    try:
        from jwt import PyJWK
        pem = settings.JWT_PUBLIC_KEY.replace("\\n", "\n")
        jwk = PyJWK.from_pem(pem.encode())
        key_dict = jwk.key.export(as_dict=True)
        key_dict["use"] = "sig"
        key_dict["alg"] = _get_effective_algorithm()
        key_dict["kid"] = hashlib.sha256(pem.encode()).hexdigest()[:16]
        return key_dict
    except Exception:
        logger.warning("jwks_export_failed")
        return None


def create_refresh_token() -> tuple[str, str]:
    """Create a refresh token.

    Returns:
        Tuple of (raw_token, token_hash). Store the hash in DB, send the raw token to client.
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


def generate_secure_token() -> tuple[str, str]:
    """Generate a secure token for email verification, password reset, etc.

    Returns:
        Tuple of (raw_token, token_hash). Send raw_token to user, store hash in DB.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    """Hash a raw token for DB lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()
