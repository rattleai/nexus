"""OAuth 2.1 metadata discovery per RFC 9728 / 8414 / 7591 + OIDC Discovery 1.0.

Implements the full discovery walk that the 2025-11-25 MCP spec mandates:

    MCP server URL
        │
        │  1. HEAD / → 401 + WWW-Authenticate with resource_metadata link
        ▼
    Protected Resource Metadata (RFC 9728)
        │
        │  2. authorization_servers[0]
        ▼
    /.well-known/oauth-authorization-server (RFC 8414)
    or /.well-known/openid-configuration (OIDC Discovery 1.0)
        │
        ▼
    AuthorizationMetadata
        { authorize_url, token_url, registration_endpoint, scopes_supported,
          code_challenge_methods_supported, token_endpoint_auth_methods_supported }

Also implements RFC 7591 Dynamic Client Registration so tenants can
self-register OAuth clients without human intervention — the critical
unlock for multi-tenancy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import ConnectorDefinition
from app.core.url_validation import validate_url

logger = structlog.stdlib.get_logger()

# Discovery cache TTL — rediscover if older than this
_DISCOVERY_TTL = timedelta(hours=24)


class DiscoveryError(Exception):
    """Raised when OAuth discovery fails."""


@dataclass(frozen=True)
class AuthorizationMetadata:
    """Unified metadata blob gathered from RFC 9728 + 8414 / OIDC."""

    issuer: str
    authorize_url: str
    token_url: str
    registration_endpoint: str | None
    userinfo_endpoint: str | None
    revocation_endpoint: str | None
    scopes_supported: list[str] | None
    response_types_supported: list[str] | None
    grant_types_supported: list[str] | None
    code_challenge_methods_supported: list[str] | None
    token_endpoint_auth_methods_supported: list[str] | None

    def to_cache(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "authorize_url": self.authorize_url,
            "token_url": self.token_url,
            "registration_endpoint": self.registration_endpoint,
            "userinfo_url": self.userinfo_endpoint,
            "revoke_url": self.revocation_endpoint,
            "scopes_supported": self.scopes_supported,
            "response_types_supported": self.response_types_supported,
            "grant_types_supported": self.grant_types_supported,
            "code_challenge_methods_supported": self.code_challenge_methods_supported,
            "token_endpoint_auth_methods_supported": self.token_endpoint_auth_methods_supported,
        }

    @classmethod
    def from_cache(cls, data: dict[str, Any]) -> AuthorizationMetadata:
        return cls(
            issuer=data.get("issuer", ""),
            authorize_url=data.get("authorize_url", ""),
            token_url=data.get("token_url", ""),
            registration_endpoint=data.get("registration_endpoint"),
            userinfo_endpoint=data.get("userinfo_url"),
            revocation_endpoint=data.get("revoke_url"),
            scopes_supported=data.get("scopes_supported"),
            response_types_supported=data.get("response_types_supported"),
            grant_types_supported=data.get("grant_types_supported"),
            code_challenge_methods_supported=data.get("code_challenge_methods_supported"),
            token_endpoint_auth_methods_supported=data.get("token_endpoint_auth_methods_supported"),
        )


async def discover_authorization(
    connector_def: ConnectorDefinition,
    *,
    db: AsyncSession,
    force_refresh: bool = False,
) -> AuthorizationMetadata:
    """Discover OAuth metadata for an MCP connector and cache the result.

    Uses the connector's ``discovery_cache`` column if it's recent enough;
    otherwise performs a fresh discovery walk.
    """
    # Cache hit?
    if (
        not force_refresh
        and connector_def.discovery_cache
        and connector_def.discovery_refreshed_at
        and connector_def.discovery_refreshed_at > datetime.now(UTC) - _DISCOVERY_TTL
    ):
        return AuthorizationMetadata.from_cache(connector_def.discovery_cache)

    mcp_cfg = connector_def.mcp_config or {}
    auth_cfg = connector_def.auth_config or {}

    server_url = mcp_cfg.get("server_url") or auth_cfg.get("issuer")
    if not server_url:
        # No MCP URL: fall back to manifest-declared authorize/token URLs
        if auth_cfg.get("authorize_url") and auth_cfg.get("token_url"):
            metadata = AuthorizationMetadata(
                issuer=auth_cfg.get("issuer", ""),
                authorize_url=auth_cfg["authorize_url"],
                token_url=auth_cfg["token_url"],
                registration_endpoint=auth_cfg.get("registration_endpoint"),
                userinfo_endpoint=auth_cfg.get("userinfo_url"),
                revocation_endpoint=auth_cfg.get("revoke_url"),
                scopes_supported=auth_cfg.get("scopes"),
                response_types_supported=None,
                grant_types_supported=None,
                code_challenge_methods_supported=(
                    ["S256"] if auth_cfg.get("pkce_required") else None
                ),
                token_endpoint_auth_methods_supported=None,
            )
            await _persist_cache(connector_def, metadata, db)
            return metadata
        raise DiscoveryError(
            f"Connector '{connector_def.slug}' has no server_url for discovery "
            f"and no fallback authorize_url/token_url in auth_config."
        )

    validate_url(server_url)

    prm = await _fetch_protected_resource_metadata(server_url)
    if prm is None:
        raise DiscoveryError(
            f"No RFC 9728 Protected Resource Metadata found for {server_url}"
        )

    authorization_servers = prm.get("authorization_servers") or []
    if not authorization_servers:
        raise DiscoveryError(
            f"PRM for {server_url} does not list any authorization_servers"
        )

    as_url = authorization_servers[0]
    as_metadata = await _fetch_authorization_server_metadata(as_url)
    if as_metadata is None:
        raise DiscoveryError(
            f"No RFC 8414 / OIDC metadata found at {as_url}"
        )

    metadata = AuthorizationMetadata(
        issuer=as_metadata.get("issuer", as_url),
        authorize_url=as_metadata.get("authorization_endpoint", ""),
        token_url=as_metadata.get("token_endpoint", ""),
        registration_endpoint=as_metadata.get("registration_endpoint"),
        userinfo_endpoint=as_metadata.get("userinfo_endpoint"),
        revocation_endpoint=as_metadata.get("revocation_endpoint"),
        scopes_supported=as_metadata.get("scopes_supported"),
        response_types_supported=as_metadata.get("response_types_supported"),
        grant_types_supported=as_metadata.get("grant_types_supported"),
        code_challenge_methods_supported=as_metadata.get(
            "code_challenge_methods_supported"
        ),
        token_endpoint_auth_methods_supported=as_metadata.get(
            "token_endpoint_auth_methods_supported"
        ),
    )

    if not metadata.authorize_url or not metadata.token_url:
        raise DiscoveryError(
            f"Authorization server metadata for {as_url} is missing "
            f"authorization_endpoint or token_endpoint"
        )

    await _persist_cache(connector_def, metadata, db)
    return metadata


async def dynamic_register_client(
    *,
    metadata: AuthorizationMetadata,
    client_name: str,
    redirect_uris: list[str],
) -> tuple[str, str]:
    """Run RFC 7591 Dynamic Client Registration and return (client_id, client_secret)."""
    if not metadata.registration_endpoint:
        raise DiscoveryError(
            "Authorization server does not expose a DCR registration_endpoint"
        )

    validate_url(metadata.registration_endpoint)

    body: dict[str, Any] = {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    if metadata.scopes_supported:
        body["scope"] = " ".join(metadata.scopes_supported)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(metadata.registration_endpoint, json=body)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise DiscoveryError(
            f"Dynamic client registration failed: {str(exc)[:200]}"
        ) from exc

    client_id = data.get("client_id")
    client_secret = data.get("client_secret", "")
    if not client_id:
        raise DiscoveryError("DCR response missing client_id")

    logger.info(
        "oauth_client_registered",
        endpoint=metadata.registration_endpoint,
        client_id_suffix=client_id[-4:] if len(client_id) >= 4 else "",
    )
    return client_id, client_secret


async def _fetch_protected_resource_metadata(
    server_url: str,
) -> dict[str, Any] | None:
    """Fetch RFC 9728 Protected Resource Metadata.

    The client first attempts to access the MCP server; if it returns 401
    with a ``WWW-Authenticate`` header, the header's ``resource_metadata``
    parameter points at the PRM document. As a fallback, we try the
    standard ``/.well-known/oauth-protected-resource`` path.
    """
    parsed = urlparse(server_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        try:
            resp = await client.get(server_url)
        except Exception:
            resp = None

        if resp is not None and resp.status_code == 401:
            www_auth = resp.headers.get("WWW-Authenticate", "")
            for segment in www_auth.split(","):
                if "resource_metadata" in segment:
                    rm_url = segment.split("=", 1)[1].strip().strip('"')
                    try:
                        rm_resp = await client.get(rm_url)
                        if rm_resp.status_code == 200:
                            return rm_resp.json()
                    except Exception:
                        pass

        # Fallback: well-known path
        fallback_url = urljoin(base, "/.well-known/oauth-protected-resource")
        try:
            fallback_resp = await client.get(fallback_url)
            if fallback_resp.status_code == 200:
                return fallback_resp.json()
        except Exception:
            pass

    return None


async def _fetch_authorization_server_metadata(
    as_url: str,
) -> dict[str, Any] | None:
    """Fetch RFC 8414 Authorization Server Metadata or OIDC Discovery 1.0."""
    parsed = urlparse(as_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    candidates = [
        # RFC 8414
        urljoin(base, "/.well-known/oauth-authorization-server"),
        # OIDC Discovery 1.0
        urljoin(base, "/.well-known/openid-configuration"),
    ]
    # If as_url has a path, also try {as_url}/.well-known/*
    if parsed.path and parsed.path != "/":
        candidates.insert(0, urljoin(base, parsed.path.rstrip("/") + "/.well-known/oauth-authorization-server"))
        candidates.insert(1, urljoin(base, parsed.path.rstrip("/") + "/.well-known/openid-configuration"))

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue

    return None


async def _persist_cache(
    connector_def: ConnectorDefinition,
    metadata: AuthorizationMetadata,
    db: AsyncSession,
) -> None:
    connector_def.discovery_cache = metadata.to_cache()
    connector_def.discovery_refreshed_at = datetime.now(UTC)
    connector_def.registration_endpoint = metadata.registration_endpoint
    await db.flush()
    logger.info(
        "oauth_discovery_cached",
        slug=connector_def.slug,
        issuer=metadata.issuer,
    )
