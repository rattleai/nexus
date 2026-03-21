"""OAuth social login provider abstraction.

Handles provider-specific configuration, authorization URL generation,
code-to-token exchange, and user profile fetching for Google and GitHub.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

_STATE_TTL_SECONDS = 600  # 10 minutes


@dataclass(frozen=True)
class OAuthProviderConfig:
    authorize_url: str
    token_url: str
    userinfo_url: str
    client_id: str
    client_secret: str
    scopes: str


@dataclass
class OAuthUserProfile:
    provider: str
    provider_user_id: str
    email: str
    display_name: str | None = None
    avatar_url: str | None = None


def _build_providers() -> dict[str, OAuthProviderConfig]:
    providers: dict[str, OAuthProviderConfig] = {}
    if settings.OAUTH_GOOGLE_CLIENT_ID and settings.OAUTH_GOOGLE_CLIENT_SECRET:
        providers["google"] = OAuthProviderConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
            client_id=settings.OAUTH_GOOGLE_CLIENT_ID,
            client_secret=settings.OAUTH_GOOGLE_CLIENT_SECRET,
            scopes="openid email profile",
        )
    if settings.OAUTH_GITHUB_CLIENT_ID and settings.OAUTH_GITHUB_CLIENT_SECRET:
        providers["github"] = OAuthProviderConfig(
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            client_id=settings.OAUTH_GITHUB_CLIENT_ID,
            client_secret=settings.OAUTH_GITHUB_CLIENT_SECRET,
            scopes="user:email",
        )
    return providers


def get_configured_providers() -> list[str]:
    """Return list of provider names that have credentials configured."""
    return list(_build_providers().keys())


def get_provider_config(provider: str) -> OAuthProviderConfig:
    """Get config for a provider, raising ValueError if not configured."""
    providers = _build_providers()
    if provider not in providers:
        raise ValueError(f"OAuth provider '{provider}' is not configured")
    return providers[provider]


async def generate_authorize_url(
    provider: str,
    redirect_uri: str,
    linking_user_id: str | None = None,
) -> str:
    """Build an authorization URL and store state in Redis.

    Returns the full authorization URL the client should redirect to.
    """
    from app.core.redis import redis_pool

    config = get_provider_config(provider)
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()

    # HMAC-sign linking_user_id to prevent tampering if state leaks
    linking_user_id_hmac = None
    if linking_user_id:
        linking_user_id_hmac = hmac.new(
            settings.SECRET_KEY.encode(), linking_user_id.encode(), hashlib.sha256,
        ).hexdigest()

    state_data = json.dumps({
        "provider": provider,
        "redirect_uri": redirect_uri,
        "linking_user_id": linking_user_id,
        "linking_user_id_hmac": linking_user_id_hmac,
    })
    await redis_pool.setex(f"oauth:state:{state_hash}", _STATE_TTL_SECONDS, state_data)

    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": config.scopes,
        "state": state,
        "response_type": "code",
    }

    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "consent"

    return f"{config.authorize_url}?{urlencode(params)}"


async def validate_state(state: str) -> dict | None:
    """Atomically retrieve and delete state from Redis to prevent replay.

    Uses GETDEL (Redis 6.2+) for true atomic get-and-delete.
    Returns the stored metadata dict or None if state is invalid/expired.
    """
    from app.core.redis import redis_pool

    state_hash = hashlib.sha256(state.encode()).hexdigest()
    key = f"oauth:state:{state_hash}"

    raw = await redis_pool.getdel(key)
    if not raw:
        return None
    return json.loads(raw)


async def exchange_code_for_tokens(
    provider: str,
    code: str,
    redirect_uri: str,
) -> dict:
    """Exchange an authorization code for access/refresh tokens.

    Returns the parsed token response dict.
    """
    config = get_provider_config(provider)

    headers: dict[str, str] = {}
    if provider == "github":
        headers["Accept"] = "application/json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            config.token_url,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_user_profile(provider: str, access_token: str) -> OAuthUserProfile:
    """Fetch and normalize the user's profile from the OAuth provider.

    For GitHub, makes an additional call to /user/emails when the primary
    email is null on the /user response, and only trusts verified emails.
    """
    config = get_provider_config(provider)

    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        if provider == "github":
            headers["Accept"] = "application/vnd.github+json"

        resp = await client.get(config.userinfo_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if provider == "google":
        if not data.get("email_verified"):
            raise ValueError("Google account email is not verified")
        return OAuthUserProfile(
            provider="google",
            provider_user_id=str(data["sub"]),
            email=data["email"],
            display_name=data.get("name"),
            avatar_url=data.get("picture"),
        )

    if provider == "github":
        email = data.get("email")

        # GitHub may not return email on /user — fetch from /user/emails
        if not email:
            async with httpx.AsyncClient(timeout=10.0) as client:
                emails_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                emails_resp.raise_for_status()
                emails = emails_resp.json()

                # Find primary verified email
                for e in emails:
                    if e.get("primary") and e.get("verified"):
                        email = e["email"]
                        break

                # Fallback: any verified email
                if not email:
                    for e in emails:
                        if e.get("verified"):
                            email = e["email"]
                            break

        if not email:
            raise ValueError("GitHub account has no verified email address")

        return OAuthUserProfile(
            provider="github",
            provider_user_id=str(data["id"]),
            email=email,
            display_name=data.get("name") or data.get("login"),
            avatar_url=data.get("avatar_url"),
        )

    raise ValueError(f"Unsupported provider: {provider}")


def verify_linking_user_id(state_data: dict) -> bool:
    """Verify the HMAC on linking_user_id in state data."""
    linking_user_id = state_data.get("linking_user_id")
    stored_hmac = state_data.get("linking_user_id_hmac")
    if not linking_user_id or not stored_hmac:
        return False
    expected = hmac.new(
        settings.SECRET_KEY.encode(), linking_user_id.encode(), hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, stored_hmac)
