"""Per-tenant OAuth app credential management.

Each tenant registers its own OAuth application (client_id / client_secret)
for each connector slug that requires them. Replaces the insecure pattern
of storing these in the global ``connector_definitions.auth_config`` JSONB.

Secrets are encrypted at rest via ``app.core.encryption`` (AES-256-GCM v2)
and isolated by RLS. Read access is scoped to the tenant context.

Usage::

    from app.connectors.app_credentials import app_credential_manager

    # Register an OAuth app for a tenant
    await app_credential_manager.register(
        tenant_id=tenant.id,
        connector_slug="slack",
        client_id="abc123",
        client_secret="xyz789",
        db=db,
    )

    # Fetch decrypted credentials for an OAuth flow
    creds = await app_credential_manager.get(
        tenant_id=tenant.id,
        connector_slug="slack",
        db=db,
    )
    if creds:
        client_id, client_secret = creds.client_id, creds.client_secret
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import ConnectorAppCredential
from app.core.encryption import decrypt, encrypt

logger = structlog.stdlib.get_logger()


class AppCredentialError(Exception):
    """Raised when per-tenant app credential operations fail."""


@dataclass(frozen=True)
class DecryptedAppCredentials:
    """Decrypted view of an app credential record. Never persist this."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    connector_slug: str
    client_id: str | None
    client_secret: str | None
    webhook_secret: str | None
    redirect_uri_override: str | None
    extra_config: dict[str, Any] | None


class AppCredentialManager:
    """Manages encrypted per-tenant OAuth app credentials."""

    async def register(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        client_id: str | None,
        client_secret: str | None,
        webhook_secret: str | None = None,
        redirect_uri_override: str | None = None,
        extra_config: dict[str, Any] | None = None,
        created_by_user_id: uuid.UUID | None = None,
        db: AsyncSession,
    ) -> ConnectorAppCredential:
        """Register or update an OAuth app for this tenant + connector.

        Upserts the row — calling ``register`` again replaces existing
        credentials, which is the rotation path.
        """
        existing = await self._get_row(tenant_id, connector_slug, db)

        if existing is not None:
            existing.client_id_enc = encrypt(client_id) if client_id else None
            existing.client_secret_enc = encrypt(client_secret) if client_secret else None
            if webhook_secret is not None:
                existing.webhook_secret_enc = encrypt(webhook_secret) if webhook_secret else None
            existing.redirect_uri_override = redirect_uri_override
            if extra_config is not None:
                existing.extra_config = extra_config
            await db.flush()
            logger.info(
                "connector_app_credentials_rotated",
                tenant_id=str(tenant_id),
                connector_slug=connector_slug,
            )
            return existing

        row = ConnectorAppCredential(
            tenant_id=tenant_id,
            connector_slug=connector_slug,
            client_id_enc=encrypt(client_id) if client_id else None,
            client_secret_enc=encrypt(client_secret) if client_secret else None,
            webhook_secret_enc=encrypt(webhook_secret) if webhook_secret else None,
            redirect_uri_override=redirect_uri_override,
            extra_config=extra_config,
            created_by_user_id=created_by_user_id,
        )
        db.add(row)
        await db.flush()
        logger.info(
            "connector_app_credentials_registered",
            tenant_id=str(tenant_id),
            connector_slug=connector_slug,
        )
        return row

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        db: AsyncSession,
    ) -> DecryptedAppCredentials | None:
        """Return decrypted credentials for a tenant+connector, or None.

        The returned dataclass is a detached view — never persist it.
        """
        row = await self._get_row(tenant_id, connector_slug, db)
        if row is None:
            return None

        try:
            return DecryptedAppCredentials(
                id=row.id,
                tenant_id=row.tenant_id,
                connector_slug=row.connector_slug,
                client_id=decrypt(row.client_id_enc) if row.client_id_enc else None,
                client_secret=decrypt(row.client_secret_enc) if row.client_secret_enc else None,
                webhook_secret=decrypt(row.webhook_secret_enc) if row.webhook_secret_enc else None,
                redirect_uri_override=row.redirect_uri_override,
                extra_config=row.extra_config,
            )
        except ValueError as exc:
            logger.error(
                "connector_app_credentials_decrypt_failed",
                tenant_id=str(tenant_id),
                connector_slug=connector_slug,
                error=str(exc)[:200],
            )
            raise AppCredentialError(
                "Stored app credentials could not be decrypted. Re-register the OAuth app."
            ) from exc

    async def require(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        db: AsyncSession,
    ) -> DecryptedAppCredentials:
        """Like ``get``, but raises ``AppCredentialError`` if missing."""
        creds = await self.get(tenant_id=tenant_id, connector_slug=connector_slug, db=db)
        if creds is None:
            raise AppCredentialError(
                f"No OAuth app credentials registered for tenant "
                f"{tenant_id} and connector '{connector_slug}'. "
                f"A workspace admin must register the OAuth app first."
            )
        return creds

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        db: AsyncSession,
    ) -> bool:
        """Delete an app credential row. Returns True if a row was removed."""
        row = await self._get_row(tenant_id, connector_slug, db)
        if row is None:
            return False
        await db.delete(row)  # AsyncSession.delete is actually async in SQLAlchemy 2.x
        await db.flush()
        logger.info(
            "connector_app_credentials_deleted",
            tenant_id=str(tenant_id),
            connector_slug=connector_slug,
        )
        return True

    async def _get_row(
        self,
        tenant_id: uuid.UUID,
        connector_slug: str,
        db: AsyncSession,
    ) -> ConnectorAppCredential | None:
        result = await db.execute(
            select(ConnectorAppCredential).where(
                ConnectorAppCredential.tenant_id == tenant_id,
                ConnectorAppCredential.connector_slug == connector_slug,
            )
        )
        return result.scalar_one_or_none()


app_credential_manager = AppCredentialManager()
