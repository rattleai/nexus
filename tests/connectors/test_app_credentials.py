"""P0.1: Per-tenant OAuth app credential encryption & isolation tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.app_credentials import (
    AppCredentialError,
    DecryptedAppCredentials,
    app_credential_manager,
)
from app.connectors.models import ConnectorAppCredential


class FakeDB:
    """Minimal async-DB stub that stores rows in a dict."""

    def __init__(self) -> None:
        self._rows: list[ConnectorAppCredential] = []
        self.flush = AsyncMock()

    def add(self, row: ConnectorAppCredential) -> None:
        if not row.id:
            row.id = uuid.uuid4()
        self._rows.append(row)

    async def delete(self, row: ConnectorAppCredential) -> None:
        self._rows = [r for r in self._rows if r.id != row.id]

    async def execute(self, stmt):  # noqa: ANN001
        result = MagicMock()
        tenant_id, slug = _stmt_tenant_slug(stmt)
        for row in self._rows:
            if row.tenant_id == tenant_id and row.connector_slug == slug:
                result.scalar_one_or_none.return_value = row
                return result
        result.scalar_one_or_none.return_value = None
        return result


def _stmt_tenant_slug(stmt) -> tuple[uuid.UUID, str]:  # noqa: ANN001
    # The manager always filters by (tenant_id, connector_slug).
    # Extract them from the compiled clause.
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    text = str(compiled)
    # This is test-only parsing — keep it simple
    params = stmt.compile().params
    tid = params.get("tenant_id_1") or params.get("tenant_id")
    slug = params.get("connector_slug_1") or params.get("connector_slug")
    if isinstance(tid, str):
        tid = uuid.UUID(tid)
    return tid, str(slug)


@pytest.mark.asyncio
async def test_register_and_get_roundtrips_encryption():
    db = FakeDB()
    tenant = uuid.uuid4()

    row = await app_credential_manager.register(
        tenant_id=tenant,
        connector_slug="slack",
        client_id="my-client-id",
        client_secret="s3cret!",
        webhook_secret="whsec_xyz",
        db=db,
    )
    assert row.client_id_enc and row.client_id_enc != "my-client-id"
    assert row.client_secret_enc and row.client_secret_enc != "s3cret!"

    got = await app_credential_manager.get(
        tenant_id=tenant, connector_slug="slack", db=db,
    )
    assert isinstance(got, DecryptedAppCredentials)
    assert got.client_id == "my-client-id"
    assert got.client_secret == "s3cret!"
    assert got.webhook_secret == "whsec_xyz"


@pytest.mark.asyncio
async def test_register_again_rotates_secrets():
    db = FakeDB()
    tenant = uuid.uuid4()

    await app_credential_manager.register(
        tenant_id=tenant,
        connector_slug="slack",
        client_id="old",
        client_secret="old-secret",
        db=db,
    )
    row = await app_credential_manager.register(
        tenant_id=tenant,
        connector_slug="slack",
        client_id="new",
        client_secret="new-secret",
        db=db,
    )

    got = await app_credential_manager.get(
        tenant_id=tenant, connector_slug="slack", db=db,
    )
    assert got.client_id == "new"
    assert got.client_secret == "new-secret"


@pytest.mark.asyncio
async def test_require_raises_when_missing():
    db = FakeDB()
    tenant = uuid.uuid4()
    with pytest.raises(AppCredentialError):
        await app_credential_manager.require(
            tenant_id=tenant, connector_slug="slack", db=db,
        )


@pytest.mark.asyncio
async def test_tenant_isolation():
    db = FakeDB()
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    await app_credential_manager.register(
        tenant_id=tenant_a,
        connector_slug="slack",
        client_id="alice-client",
        client_secret="alice-secret",
        db=db,
    )
    await app_credential_manager.register(
        tenant_id=tenant_b,
        connector_slug="slack",
        client_id="bob-client",
        client_secret="bob-secret",
        db=db,
    )

    got_a = await app_credential_manager.get(
        tenant_id=tenant_a, connector_slug="slack", db=db,
    )
    got_b = await app_credential_manager.get(
        tenant_id=tenant_b, connector_slug="slack", db=db,
    )

    assert got_a.client_id == "alice-client"
    assert got_b.client_id == "bob-client"
    assert got_a.client_id != got_b.client_id
    assert got_a.client_secret != got_b.client_secret


@pytest.mark.asyncio
async def test_delete_removes_row():
    db = FakeDB()
    tenant = uuid.uuid4()
    await app_credential_manager.register(
        tenant_id=tenant,
        connector_slug="slack",
        client_id="c",
        client_secret="s",
        db=db,
    )
    removed = await app_credential_manager.delete(
        tenant_id=tenant, connector_slug="slack", db=db,
    )
    assert removed is True
    got = await app_credential_manager.get(
        tenant_id=tenant, connector_slug="slack", db=db,
    )
    assert got is None
