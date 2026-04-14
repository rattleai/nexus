"""Credential management for connector connections.

Handles encrypted storage, transparent OAuth token refresh, and credential
lifecycle (store, retrieve, refresh, revoke).

Security hardening over PR #63:

* **P0.1** — OAuth client_id / client_secret for refresh are looked up per-tenant
  via ``ConnectorAppCredential`` instead of being read from the global
  ``connector_definitions.auth_config`` JSONB.
* **P0.4** — Token refresh is wrapped in a Redis distributed lock with a
  double-check after acquisition, so concurrent ``get_valid_token`` callers
  don't race each other into stale-refresh-token territory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.app_credentials import (
    AppCredentialError,
    app_credential_manager,
)
from app.connectors.models import (
    ConnectorDefinition,
    CredentialType,
    TenantConnection,
    TenantCredential,
)
from app.core.encryption import decrypt, encrypt
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Distributed refresh lock (P0.4)
_REFRESH_LOCK_PREFIX = "connector:refresh_lock"
_REFRESH_LOCK_TIMEOUT = 30  # lock auto-releases after N seconds
_REFRESH_LOCK_BLOCKING_TIMEOUT = 20  # max seconds to wait for the lock


class CredentialError(Exception):
    """Raised when credential operations fail."""


class CredentialManager:
    """Manages encrypted credential storage and OAuth token refresh."""

    # ── Store ────────────────────────────────────────────────

    async def store_oauth(
        self,
        *,
        connection: TenantConnection,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str] | None,
        auth_metadata: dict[str, Any] | None,
        db: AsyncSession,
    ) -> TenantCredential:
        """Encrypt and persist OAuth2 credentials for a connection."""
        now = datetime.now(UTC)
        credential = TenantCredential(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            credential_type=CredentialType.OAUTH2,
            access_token_enc=encrypt(access_token),
            refresh_token_enc=encrypt(refresh_token) if refresh_token else None,
            token_expires_at=now + timedelta(seconds=expires_in) if expires_in else None,
            granted_scopes={"scopes": scopes} if scopes else None,
            auth_metadata=auth_metadata,
            is_valid=True,
        )
        db.add(credential)
        await db.flush()
        logger.info(
            "credential_stored",
            connection_id=str(connection.id),
            credential_type="oauth2",
        )
        return credential

    async def store_api_key(
        self,
        *,
        connection: TenantConnection,
        api_key: str,
        auth_metadata: dict[str, Any] | None,
        db: AsyncSession,
    ) -> TenantCredential:
        """Encrypt and persist an API key credential."""
        credential = TenantCredential(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            credential_type=CredentialType.API_KEY,
            api_key_enc=encrypt(api_key),
            auth_metadata=auth_metadata,
            is_valid=True,
        )
        db.add(credential)
        await db.flush()
        logger.info(
            "credential_stored",
            connection_id=str(connection.id),
            credential_type="api_key",
        )
        return credential

    async def store_bearer_token(
        self,
        *,
        connection: TenantConnection,
        token: str,
        auth_metadata: dict[str, Any] | None,
        db: AsyncSession,
    ) -> TenantCredential:
        """Encrypt and persist a bearer token credential."""
        credential = TenantCredential(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            credential_type=CredentialType.BEARER_TOKEN,
            access_token_enc=encrypt(token),
            auth_metadata=auth_metadata,
            is_valid=True,
        )
        db.add(credential)
        await db.flush()
        return credential

    # ── Retrieve ─────────────────────────────────────────────

    async def get_valid_token(
        self,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> str:
        """Return a valid decrypted access token, refreshing if expired.

        For API key credentials, returns the decrypted API key.
        For OAuth2, refreshes the token if it has expired or is about
        to expire within the configured buffer window. Uses a Redis
        distributed lock to ensure concurrent callers don't race each
        other into stale-refresh-token territory (P0.4).
        """
        credential = connection.credential
        if credential is None:
            result = await db.execute(
                select(TenantCredential).where(
                    TenantCredential.connection_id == connection.id,
                )
            )
            credential = result.scalar_one_or_none()
            if credential is None:
                raise CredentialError(
                    f"No credential found for connection {connection.id}"
                )

        if not credential.is_valid:
            raise CredentialError(
                f"Credential for connection {connection.id} is marked invalid. "
                "Please re-authenticate."
            )

        # API key / bearer: just decrypt and return
        if credential.credential_type == CredentialType.API_KEY:
            if not credential.api_key_enc:
                raise CredentialError("API key credential is empty")
            return decrypt(credential.api_key_enc)

        if credential.credential_type == CredentialType.BEARER_TOKEN:
            if not credential.access_token_enc:
                raise CredentialError("Bearer token credential is empty")
            return decrypt(credential.access_token_enc)

        # OAuth2: check expiry and refresh if needed
        if credential.credential_type == CredentialType.OAUTH2:
            if self._needs_refresh(credential):
                await self._refresh_with_lock(credential, connector_def, db)

            if not credential.access_token_enc:
                raise CredentialError("OAuth access token is empty")
            return decrypt(credential.access_token_enc)

        raise CredentialError(f"Unknown credential type: {credential.credential_type}")

    def _needs_refresh(self, credential: TenantCredential) -> bool:
        """True when the OAuth access token is expired or nearly so."""
        if not credential.token_expires_at:
            return False
        if not credential.refresh_token_enc:
            return False
        buffer = timedelta(
            seconds=settings.CONNECTOR_CREDENTIAL_REFRESH_BUFFER_SECONDS
        )
        return credential.token_expires_at < datetime.now(UTC) + buffer

    async def _refresh_with_lock(
        self,
        credential: TenantCredential,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        """Acquire a Redis lock, re-read the credential, then refresh if needed.

        Double-check is essential: another worker may have refreshed the
        credential while we were waiting for the lock.
        """
        lock_key = f"{_REFRESH_LOCK_PREFIX}:{credential.id}"
        lock = redis_pool.lock(
            lock_key,
            timeout=_REFRESH_LOCK_TIMEOUT,
            blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT,
        )

        acquired = False
        try:
            acquired = await lock.acquire()
        except Exception:
            # Redis down — fail open so we at least attempt refresh
            logger.warning(
                "credential_refresh_lock_redis_error",
                credential_id=str(credential.id),
                exc_info=True,
            )
            acquired = False

        if not acquired:
            # Lock contention — rely on the other refresher. Re-read and check.
            await db.refresh(credential)
            if self._needs_refresh(credential):
                raise CredentialError(
                    "OAuth token refresh is contended; please retry shortly."
                )
            return

        try:
            await db.refresh(credential)
            if not self._needs_refresh(credential):
                # Another worker already refreshed it
                return
            await self.refresh_oauth(credential, connector_def, db)
        finally:
            try:
                await lock.release()
            except Exception:
                logger.debug(
                    "credential_refresh_lock_release_failed",
                    credential_id=str(credential.id),
                    exc_info=True,
                )

    # ── Refresh ──────────────────────────────────────────────

    async def refresh_oauth(
        self,
        credential: TenantCredential,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        """Refresh an OAuth2 access token using the stored refresh token.

        Uses per-tenant OAuth app credentials (P0.1) — never reads
        client_id / client_secret from the global connector definition.
        """
        if not credential.refresh_token_enc:
            credential.is_valid = False
            credential.refresh_error = "No refresh token available"
            await db.flush()
            raise CredentialError("No refresh token available for refresh")

        from app.connectors.oauth_flow import _effective_auth_config

        auth_config = _effective_auth_config(connector_def)
        token_url = auth_config.get("token_url")
        if not token_url:
            raise CredentialError(
                f"Connector {connector_def.slug} has no token_url"
            )

        try:
            app_creds = await app_credential_manager.require(
                tenant_id=credential.tenant_id,
                connector_slug=connector_def.slug,
                db=db,
            )
        except AppCredentialError as exc:
            credential.is_valid = False
            credential.refresh_error = str(exc)[:500]
            await db.flush()
            raise CredentialError(str(exc)) from exc

        refresh_token = decrypt(credential.refresh_token_enc)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    token_url,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": app_creds.client_id or "",
                        "client_secret": app_creds.client_secret or "",
                    },
                )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error(
                "credential_refresh_failed",
                connection_id=str(credential.connection_id),
                error=str(exc)[:200],
            )
            credential.is_valid = False
            credential.refresh_error = str(exc)[:500]
            await db.flush()
            raise CredentialError(
                "Token refresh failed. Please re-authenticate."
            ) from exc

        now = datetime.now(UTC)
        credential.access_token_enc = encrypt(data["access_token"])
        if data.get("refresh_token"):
            credential.refresh_token_enc = encrypt(data["refresh_token"])
        if data.get("expires_in"):
            credential.token_expires_at = now + timedelta(seconds=data["expires_in"])
        credential.last_refreshed_at = now
        credential.refresh_error = None
        credential.is_valid = True
        await db.flush()

        logger.info(
            "credential_refreshed",
            connection_id=str(credential.connection_id),
        )

    # ── Revoke ───────────────────────────────────────────────

    async def revoke(
        self,
        credential: TenantCredential,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> None:
        """Best-effort revoke tokens at the provider, then clear stored secrets."""
        from app.connectors.oauth_flow import _effective_auth_config

        auth_config = _effective_auth_config(connector_def)
        revoke_url = auth_config.get("revoke_url")

        if revoke_url and credential.access_token_enc:
            try:
                token = decrypt(credential.access_token_enc)
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(revoke_url, data={"token": token})
            except Exception:
                logger.warning(
                    "credential_revocation_failed",
                    connection_id=str(credential.connection_id),
                )

        credential.access_token_enc = None
        credential.refresh_token_enc = None
        credential.api_key_enc = None
        credential.is_valid = False
        await db.flush()

        logger.info(
            "credential_revoked",
            connection_id=str(credential.connection_id),
        )


credential_manager = CredentialManager()
