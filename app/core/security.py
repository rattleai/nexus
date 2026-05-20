"""Password hashing and JWT token utilities.

Uses passlib+argon2id for password hashing and PyJWT for token management.
Argon2id is the recommended KDF (OWASP, RFC 9106) — resistant to both
GPU/ASIC attacks and side-channel attacks, with no 72-byte truncation issue.

Supports RS256 (asymmetric) JWT signing for production multi-service
architectures, with HS256 fallback for development.
"""

import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import structlog
from passlib.context import CryptContext

from app.config import settings

logger = structlog.stdlib.get_logger()

# ---------------------------------------------------------------------------
# Short-lived in-memory cache for "not revoked" token checks.
#
# When Redis is healthy, we cache negative revocation results (token NOT
# revoked) for a few seconds.  If Redis becomes unreachable, recently-verified
# tokens continue to work instead of instantly logging out every user.
#
# ONLY "not revoked" results are cached — positive revocations are never
# cached so that token revocation remains immediate.
# ---------------------------------------------------------------------------
_NOT_REVOKED_CACHE: dict[str, float] = {}
_NOT_REVOKED_CACHE_TTL = 5  # seconds
_NOT_REVOKED_CACHE_MAX = 2000


def _cache_check(key: str) -> bool | None:
    """Return False (not revoked) if cached and fresh, else None."""
    ts = _NOT_REVOKED_CACHE.get(key)
    if ts is not None and (time.monotonic() - ts) < _NOT_REVOKED_CACHE_TTL:
        return False
    return None


def _cache_set(key: str) -> None:
    """Cache a 'not revoked' result."""
    if len(_NOT_REVOKED_CACHE) >= _NOT_REVOKED_CACHE_MAX:
        # Simple eviction: drop all entries (rare — ~2k active tokens needed)
        _NOT_REVOKED_CACHE.clear()
    _NOT_REVOKED_CACHE[key] = time.monotonic()

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
    defaults = {
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
        "jti": jti,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    # Preserve caller-supplied fields (e.g., type="mfa_pending", amr=[...])
    for k, v in defaults.items():
        if k not in to_encode:
            to_encode[k] = v
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
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


async def is_token_revoked(jti: str) -> bool:
    """Check if a JWT access token has been revoked via Redis blacklist.

    Uses a short in-memory cache for 'not revoked' results so that a brief
    Redis outage does not instantly log out every user.  Positive revocations
    (token IS revoked) are never cached — revocation takes effect immediately.
    """
    cache_key = f"jti:{jti}"

    # Fast path: recently verified as not-revoked
    cached = _cache_check(cache_key)
    if cached is not None:
        return cached

    try:
        from app.core.redis import redis_pool
        result = await redis_pool.get(f"jwt:revoked:{jti}")
        if result is not None:
            # Token IS revoked — remove any stale cache entry
            _NOT_REVOKED_CACHE.pop(cache_key, None)
            return True
        # Token is not revoked — cache briefly
        _cache_set(cache_key)
        return False
    except Exception:
        # Redis unavailable — use cached "not revoked" if we have one
        if cache_key in _NOT_REVOKED_CACHE:
            logger.warning("token_revocation_redis_unavailable_using_cache", jti=jti)
            return False
        # No cache entry — fail closed (safe default)
        logger.error("token_revocation_check_failed_closing", jti=jti)
        return True


async def revoke_access_token(jti: str, ttl_seconds: int | None = None) -> None:
    """Add a JWT access token to the revocation blacklist.

    The blacklist entry expires when the token would naturally expire,
    preventing unbounded Redis memory growth.

    Raises RuntimeError on Redis failure so the caller can surface the
    error (e.g., return 503 on security-critical paths like password reset).
    """
    if not jti:
        return
    try:
        from app.core.redis import redis_pool
        ttl = ttl_seconds or (settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        await redis_pool.setex(f"jwt:revoked:{jti}", ttl, "1")
    except Exception as exc:
        logger.error("token_revocation_failed", jti=jti, exc_info=True)
        raise RuntimeError("Token revocation failed — Redis unavailable") from exc


async def revoke_all_user_tokens(user_id: str) -> None:
    """Mark all access tokens for a user as revoked by setting a 'revoked since' timestamp.

    Any token issued before this timestamp will be rejected.

    Raises RuntimeError on Redis failure so the caller can surface the error.
    """
    try:
        from app.core.redis import redis_pool
        ttl = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        await redis_pool.setex(f"jwt:user_revoked:{user_id}", ttl, str(int(datetime.now(UTC).timestamp())))
    except Exception as exc:
        logger.error("user_token_revocation_failed", user_id=user_id, exc_info=True)
        raise RuntimeError("User token revocation failed — Redis unavailable") from exc


async def is_user_token_revoked(user_id: str, issued_at: int) -> bool:
    """Check if a user's tokens issued before a certain time have been revoked.

    Same caching strategy as is_token_revoked — brief Redis outages do not
    cause mass logouts for users whose tokens were recently verified.
    """
    cache_key = f"user:{user_id}:{issued_at}"

    cached = _cache_check(cache_key)
    if cached is not None:
        return cached

    try:
        from app.core.redis import redis_pool
        revoked_since = await redis_pool.get(f"jwt:user_revoked:{user_id}")
        if revoked_since and issued_at < int(revoked_since):
            _NOT_REVOKED_CACHE.pop(cache_key, None)
            return True
        _cache_set(cache_key)
        return False
    except Exception:
        if cache_key in _NOT_REVOKED_CACHE:
            logger.warning("user_revocation_redis_unavailable_using_cache", user_id=user_id)
            return False
        logger.error("user_revocation_check_failed_closing", user_id=user_id)
        return True


def get_jwks_public_key() -> dict | None:
    """Return the primary public key in JWK format for the /.well-known/jwks.json endpoint."""
    keys = get_jwks_key_set()
    return keys[0] if keys else None


def get_jwks_key_set() -> list[dict]:
    """Return all public keys in JWK format for the /.well-known/jwks.json endpoint.

    Supports multi-key JWKS for seamless key rotation. Returns both the
    current key and any previous key (JWT_PUBLIC_KEY_PREVIOUS) so that
    tokens signed with the old key remain valid during rotation.
    """
    if _get_effective_algorithm() not in ("RS256", "ES256"):
        return []

    keys = []

    # Current key
    if settings.JWT_PUBLIC_KEY:
        key = _export_jwk(settings.JWT_PUBLIC_KEY, kid_suffix="current")
        if key:
            keys.append(key)

    # Previous key (for rotation)
    prev_key_pem = getattr(settings, "JWT_PUBLIC_KEY_PREVIOUS", "")
    if prev_key_pem:
        key = _export_jwk(prev_key_pem, kid_suffix="previous")
        if key:
            keys.append(key)

    return keys


def _export_jwk(pem_key: str, kid_suffix: str = "") -> dict | None:
    """Export a PEM public key as JWK dict."""
    try:
        from jwt import PyJWK
        pem = pem_key.replace("\\n", "\n")
        jwk = PyJWK.from_pem(pem.encode())
        key_dict = jwk.key.export(as_dict=True)
        key_dict["use"] = "sig"
        key_dict["alg"] = _get_effective_algorithm()
        key_dict["kid"] = hashlib.sha256(pem.encode()).hexdigest()[:16]
        return key_dict
    except Exception:
        logger.warning("jwks_export_failed", kid_suffix=kid_suffix)
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
