"""Generalised OAuth 2.1 + PKCE flow for connector authentication.

Security hardening over the original PR #63 implementation:

* **P0.1** — OAuth client_id / client_secret are looked up per-tenant via
  ``ConnectorAppCredential`` instead of being read from the global
  ``connector_definitions.auth_config`` JSONB. Tenants must register their
  own OAuth app before users can authenticate.
* **P0.2** — The invoking user's ID is threaded through start/callback so
  the resulting ``TenantConnection`` is scoped to ``connected_by_user_id``,
  enabling per-user confused-deputy prevention downstream.
* **P0.5** — OAuth state is persisted in ``ConnectorOAuthState`` (with Redis
  as a fast read-through cache) so pending flows survive Redis restarts.
* **P1.2** — When the connector has ``discovery_cache`` populated (via
  ``oauth_discovery``), its URLs override the YAML manifest.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.app_credentials import (
    AppCredentialError,
    app_credential_manager,
)
from app.connectors.credentials import credential_manager
from app.connectors.models import (
    ConnectionStatus,
    ConnectorDefinition,
    ConnectorOAuthState,
    TenantConnection,
)
from app.core.encryption import decrypt, encrypt
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key prefix for OAuth state tokens (fast read-through cache).
# Durable state lives in ``connector_oauth_states`` table (P0.5).
_OAUTH_STATE_PREFIX = "connector:oauth_state"
_OAUTH_STATE_TTL_SECONDS = 600


class OAuthFlowError(Exception):
    """Raised when OAuth flow operations fail."""


def _effective_auth_config(connector_def: ConnectorDefinition) -> dict[str, Any]:
    """Merge discovery cache over YAML auth_config.

    Discovery cache (from ``oauth_discovery.discover_authorization``) takes
    precedence when present, so an MCP server that implements RFC 9728/8414
    gets up-to-date endpoints without YAML rewrites.
    """
    base = dict(connector_def.auth_config or {})
    discovery = connector_def.discovery_cache or {}
    if discovery:
        for key in (
            "authorize_url",
            "token_url",
            "userinfo_url",
            "revoke_url",
            "scopes_supported",
            "code_challenge_methods_supported",
            "registration_endpoint",
        ):
            if discovery.get(key):
                base[key] = discovery[key]
    return base


class ConnectorOAuthFlow:
    """Orchestrates OAuth 2.1 authorization code flows for connectors."""

    async def start(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        redirect_uri: str,
        user_id: uuid.UUID | None = None,
        db: AsyncSession,
    ) -> dict[str, str]:
        """Build the authorization URL and store state for CSRF validation.

        Returns ``{"auth_url": "...", "state": "..."}``.
        """
        auth_config = _effective_auth_config(connector_def)
        authorize_url = auth_config.get("authorize_url")
        if not authorize_url:
            raise OAuthFlowError(
                f"Connector {connector_def.slug} has no authorize_url. "
                f"Either provide one in the YAML manifest or register the "
                f"connector so OAuth discovery (RFC 9728/8414) can populate it."
            )

        # Per-tenant OAuth app credentials (P0.1) — replaces insecure global secret
        try:
            app_creds = await app_credential_manager.require(
                tenant_id=tenant_id,
                connector_slug=connector_def.slug,
                db=db,
            )
        except AppCredentialError as exc:
            raise OAuthFlowError(str(exc)) from exc

        client_id = app_creds.client_id or ""
        if not client_id:
            raise OAuthFlowError(f"OAuth app credentials for '{connector_def.slug}' have no client_id.")

        scopes = auth_config.get("scopes", [])
        pkce_required = bool(auth_config.get("pkce_required", False))

        # Effective redirect URI (per-tenant override wins)
        if app_creds.redirect_uri_override:
            redirect_uri = app_creds.redirect_uri_override

        # Cryptographically strong state token
        state = secrets.token_urlsafe(32)

        state_payload: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "connector_slug": connector_def.slug,
            "redirect_uri": redirect_uri,
        }

        # PKCE (S256)
        code_challenge: str | None = None
        if pkce_required:
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
            )
            state_payload["code_verifier"] = code_verifier

        if user_id:
            state_payload["user_id"] = str(user_id)

        await self._store_state(
            tenant_id=tenant_id,
            connector_slug=connector_def.slug,
            state=state,
            payload=state_payload,
            db=db,
        )

        # Build the authorization URL
        params: dict[str, str] = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if scopes:
            params["scope"] = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
        if pkce_required and code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        extra = auth_config.get("extra_authorize_params", {})
        if isinstance(extra, dict):
            params.update(extra)

        auth_url = f"{authorize_url}?{urlencode(params)}"

        logger.info(
            "oauth_flow_started",
            connector=connector_def.slug,
            tenant_id=str(tenant_id),
            user_id=str(user_id) if user_id else None,
            pkce=pkce_required,
        )

        return {"auth_url": auth_url, "state": state}

    async def callback(
        self,
        *,
        connector_def: ConnectorDefinition,
        code: str,
        state: str,
        tenant_id: uuid.UUID,
        redirect_uri: str,
        db: AsyncSession,
    ) -> TenantConnection:
        """Exchange the authorization code for tokens and create a connection.

        Validates the state parameter (CSRF), exchanges the code, fetches user
        info, and persists a per-user ``TenantConnection`` + ``TenantCredential``.
        """
        stored = await self._consume_state(tenant_id=tenant_id, state=state, db=db)
        if stored is None:
            raise OAuthFlowError("Invalid or expired OAuth state")
        if stored.get("tenant_id") != str(tenant_id):
            raise OAuthFlowError("OAuth state tenant mismatch")
        if stored.get("connector_slug") != connector_def.slug:
            raise OAuthFlowError("OAuth state connector mismatch")

        auth_config = _effective_auth_config(connector_def)
        token_url = auth_config.get("token_url")
        if not token_url:
            raise OAuthFlowError(f"Connector {connector_def.slug} has no token_url")

        try:
            app_creds = await app_credential_manager.require(
                tenant_id=tenant_id,
                connector_slug=connector_def.slug,
                db=db,
            )
        except AppCredentialError as exc:
            raise OAuthFlowError(str(exc)) from exc

        token_data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": stored.get("redirect_uri", redirect_uri),
            "client_id": app_creds.client_id or "",
            "client_secret": app_creds.client_secret or "",
        }

        code_verifier = stored.get("code_verifier")
        if code_verifier:
            token_data["code_verifier"] = code_verifier

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(token_url, data=token_data)
            response.raise_for_status()
            token_response = response.json()
        except Exception as exc:
            logger.error(
                "oauth_code_exchange_failed",
                connector=connector_def.slug,
                error=str(exc)[:200],
            )
            raise OAuthFlowError("Failed to exchange authorization code with provider") from exc

        access_token = token_response.get("access_token", "")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in")
        scopes_str = token_response.get("scope", "")
        scopes = scopes_str.split() if scopes_str else None

        if not access_token:
            raise OAuthFlowError("Provider returned empty access token")

        # Optional userinfo lookup for display_name / account_identifier
        account_identifier: str | None = None
        auth_metadata: dict[str, Any] = {}

        userinfo_url = auth_config.get("userinfo_url")
        if userinfo_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        userinfo_url,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                if resp.status_code == 200:
                    user_info = resp.json()
                    account_identifier = user_info.get("email") or user_info.get("login") or user_info.get("name")
                    auth_metadata["user_info"] = user_info
            except Exception:
                logger.debug("oauth_userinfo_fetch_failed", exc_info=True)

        user_id_str = stored.get("user_id")
        connected_by_user_id = uuid.UUID(user_id_str) if user_id_str else None

        connection = TenantConnection(
            tenant_id=tenant_id,
            connector_definition_id=connector_def.id,
            display_name=account_identifier or connector_def.name,
            account_identifier=account_identifier,
            status=ConnectionStatus.ACTIVE,
            connected_by_user_id=connected_by_user_id,
        )
        db.add(connection)
        await db.flush()

        await credential_manager.store_oauth(
            connection=connection,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(expires_in) if expires_in else None,
            scopes=scopes,
            auth_metadata=auth_metadata,
            db=db,
        )

        logger.info(
            "oauth_connection_created",
            connector=connector_def.slug,
            connection_id=str(connection.id),
            tenant_id=str(tenant_id),
            user_id=str(connected_by_user_id) if connected_by_user_id else None,
            account=account_identifier,
        )

        return connection

    # ── State Store (P0.5) ───────────────────────────────────

    async def _store_state(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        state: str,
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Persist OAuth state in both Redis (fast) and Postgres (durable)."""
        payload_json = json.dumps(payload)
        payload_enc = encrypt(payload_json)

        expires_at = datetime.now(UTC) + timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)
        db.add(
            ConnectorOAuthState(
                tenant_id=tenant_id,
                state_token=state,
                connector_slug=connector_slug,
                payload_enc=payload_enc,
                expires_at=expires_at,
            )
        )
        await db.flush()

        # Fast path — Redis cache
        try:
            key = f"{_OAUTH_STATE_PREFIX}:{tenant_id}:{state}"
            await redis_pool.setex(key, _OAUTH_STATE_TTL_SECONDS, payload_json)
        except Exception:
            logger.debug("oauth_state_redis_cache_failed", exc_info=True)

    async def _consume_state(
        self,
        *,
        tenant_id: uuid.UUID,
        state: str,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        """Read and delete an OAuth state token.

        Tries Redis first, then falls back to the durable store. State is
        removed from both on successful consumption (single-use).
        """
        key = f"{_OAUTH_STATE_PREFIX}:{tenant_id}:{state}"

        # Try Redis (fast path)
        redis_payload: str | None = None
        try:
            redis_payload = await redis_pool.get(key)
        except Exception:
            logger.debug("oauth_state_redis_read_failed", exc_info=True)

        result = await db.execute(
            select(ConnectorOAuthState).where(
                ConnectorOAuthState.state_token == state,
                ConnectorOAuthState.tenant_id == tenant_id,
            )
        )
        row = result.scalar_one_or_none()

        payload_json: str | None = None
        if redis_payload:
            payload_json = redis_payload
        elif row is not None and row.expires_at > datetime.now(UTC):
            try:
                payload_json = decrypt(row.payload_enc)
            except ValueError:
                logger.warning("oauth_state_decrypt_failed", state=state)

        # Single-use — delete from both stores regardless
        with contextlib.suppress(Exception):
            await redis_pool.delete(key)

        if row is not None:
            await db.execute(delete(ConnectorOAuthState).where(ConnectorOAuthState.id == row.id))
            await db.flush()

        if payload_json is None:
            return None
        try:
            return json.loads(payload_json)
        except json.JSONDecodeError:
            logger.warning("oauth_state_payload_invalid_json", state=state)
            return None


oauth_flow = ConnectorOAuthFlow()
