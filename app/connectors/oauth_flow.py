"""Generalised OAuth 2.1 + PKCE flow for connector authentication.

Mirrors the pattern from ``app.api.v1.cloud_connections`` (start + callback)
but works with any connector definition's ``auth_config``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.credentials import credential_manager
from app.connectors.models import (
    ConnectionStatus,
    ConnectorDefinition,
    TenantConnection,
)
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key prefix for OAuth state tokens (10-minute TTL)
_OAUTH_STATE_PREFIX = "connector:oauth_state"
_OAUTH_STATE_TTL = 600


class OAuthFlowError(Exception):
    """Raised when OAuth flow operations fail."""


class ConnectorOAuthFlow:
    """Orchestrates OAuth 2.1 authorization code flows for connectors."""

    async def start(
        self,
        *,
        connector_def: ConnectorDefinition,
        tenant_id: uuid.UUID,
        redirect_uri: str,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, str]:
        """Build the authorization URL and store state for CSRF validation.

        Returns ``{"auth_url": "...", "state": "..."}``.
        """
        auth_config = connector_def.auth_config or {}
        authorize_url = auth_config.get("authorize_url")
        if not authorize_url:
            raise OAuthFlowError(
                f"Connector {connector_def.slug} has no authorize_url in auth_config"
            )

        client_id = auth_config.get("client_id", "")
        scopes = auth_config.get("scopes", [])
        pkce_required = auth_config.get("pkce_required", False)

        # Generate cryptographic state token
        state = secrets.token_urlsafe(32)

        # Build state payload stored in Redis
        state_payload = {
            "tenant_id": str(tenant_id),
            "connector_slug": connector_def.slug,
            "redirect_uri": redirect_uri,
        }

        # PKCE: generate code verifier and challenge
        code_verifier = None
        if pkce_required:
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()
            state_payload["code_verifier"] = code_verifier

        if user_id:
            state_payload["user_id"] = str(user_id)

        # Store in Redis with TTL
        import json
        state_key = f"{_OAUTH_STATE_PREFIX}:{tenant_id}:{state}"
        await redis_pool.setex(state_key, _OAUTH_STATE_TTL, json.dumps(state_payload))

        # Build authorization URL
        params: dict[str, str] = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if scopes:
            params["scope"] = " ".join(scopes) if isinstance(scopes, list) else scopes
        if pkce_required:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        # Allow extra params from auth_config
        extra_params = auth_config.get("extra_authorize_params", {})
        params.update(extra_params)

        auth_url = f"{authorize_url}?{urlencode(params)}"

        logger.info(
            "oauth_flow_started",
            connector=connector_def.slug,
            tenant_id=str(tenant_id),
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

        Validates the state parameter, exchanges the code, encrypts tokens,
        and persists a new TenantConnection + TenantCredential.
        """
        import json

        # ── Validate state (CSRF protection) ─────────────────
        state_key = f"{_OAUTH_STATE_PREFIX}:{tenant_id}:{state}"
        stored_raw = await redis_pool.get(state_key)
        if not stored_raw:
            raise OAuthFlowError("Invalid or expired OAuth state")

        stored = json.loads(stored_raw)
        if stored.get("tenant_id") != str(tenant_id):
            raise OAuthFlowError("OAuth state tenant mismatch")
        if stored.get("connector_slug") != connector_def.slug:
            raise OAuthFlowError("OAuth state connector mismatch")

        # One-time use
        await redis_pool.delete(state_key)

        # ── Exchange code for tokens ─────────────────────────
        auth_config = connector_def.auth_config or {}
        token_url = auth_config.get("token_url")
        if not token_url:
            raise OAuthFlowError(
                f"Connector {connector_def.slug} has no token_url"
            )

        token_data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": stored.get("redirect_uri", redirect_uri),
            "client_id": auth_config.get("client_id", ""),
            "client_secret": auth_config.get("client_secret", ""),
        }

        # PKCE: include code_verifier
        code_verifier = stored.get("code_verifier")
        if code_verifier:
            token_data["code_verifier"] = code_verifier

        import httpx
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
            raise OAuthFlowError(
                "Failed to exchange authorization code with provider"
            ) from exc

        # ── Extract token fields ─────────────────────────────
        access_token = token_response.get("access_token", "")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in")
        scopes_str = token_response.get("scope", "")
        scopes = scopes_str.split() if scopes_str else None

        if not access_token:
            raise OAuthFlowError("Provider returned empty access token")

        # ── Fetch user info if configured ────────────────────
        account_identifier = None
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
                    account_identifier = (
                        user_info.get("email")
                        or user_info.get("login")
                        or user_info.get("name")
                    )
                    auth_metadata["user_info"] = user_info
            except Exception:
                logger.debug("oauth_userinfo_fetch_failed", exc_info=True)

        # ── Create connection + credential ───────────────────
        user_id = stored.get("user_id")

        connection = TenantConnection(
            tenant_id=tenant_id,
            connector_definition_id=connector_def.id,
            display_name=account_identifier or connector_def.name,
            account_identifier=account_identifier,
            status=ConnectionStatus.ACTIVE,
            connected_by_user_id=uuid.UUID(user_id) if user_id else None,
        )
        db.add(connection)
        await db.flush()  # Assign UUID

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
            account=account_identifier,
        )

        return connection


# Module-level singleton
oauth_flow = ConnectorOAuthFlow()
