"""Tests for RLS WITH CHECK policies.

Verifies that tenant_isolation policies correctly block cross-tenant
INSERTs via WITH CHECK, and that FORCE ROW LEVEL SECURITY is active.

Requires a real PostgreSQL database with migrations applied.
Run with: DATABASE_TEST_URL=... pytest tests/test_rls_policies.py
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_TEST_URL"),
    reason="Requires real PostgreSQL with migrations (set DATABASE_TEST_URL)",
)


@pytest.mark.asyncio
async def test_rls_with_check_blocks_cross_tenant_insert(db: AsyncSession):
    """INSERT with wrong tenant_id must be rejected by WITH CHECK policy.

    This test runs as the superuser (test DB), so FORCE ROW LEVEL SECURITY
    is required for the policy to take effect. We simulate the app_user
    context by setting app.tenant_id via set_config.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Create tenants
    await db.execute(text(
        "INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"
    ), {"id": str(tenant_a), "name": "Tenant A", "slug": f"tenant-a-{tenant_a.hex[:8]}"})
    await db.execute(text(
        "INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"
    ), {"id": str(tenant_b), "name": "Tenant B", "slug": f"tenant-b-{tenant_b.hex[:8]}"})
    await db.flush()

    # Set RLS context to tenant A
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})

    # INSERT with tenant A's ID should succeed
    key_id_a = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO api_keys (id, tenant_id, key_hash, name) "
        "VALUES (:id, :tid, :hash, 'test')"
    ), {"id": str(key_id_a), "tid": str(tenant_a), "hash": uuid.uuid4().hex})

    # INSERT with tenant B's ID should be rejected by WITH CHECK
    key_id_b = uuid.uuid4()
    with pytest.raises(Exception):
        await db.execute(text(
            "INSERT INTO api_keys (id, tenant_id, key_hash, name) "
            "VALUES (:id, :tid, :hash, 'cross-tenant')"
        ), {"id": str(key_id_b), "tid": str(tenant_b), "hash": uuid.uuid4().hex})

    await db.rollback()


@pytest.mark.asyncio
async def test_rls_using_filters_select(db: AsyncSession):
    """SELECT should only return rows matching the current tenant context."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Create tenants
    await db.execute(text(
        "INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"
    ), {"id": str(tenant_a), "name": "Tenant A", "slug": f"rls-a-{tenant_a.hex[:8]}"})
    await db.execute(text(
        "INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"
    ), {"id": str(tenant_b), "name": "Tenant B", "slug": f"rls-b-{tenant_b.hex[:8]}"})

    # Insert keys for both tenants (as superuser, bypassing RLS for setup)
    await db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    await db.execute(text(
        "INSERT INTO api_keys (id, tenant_id, key_hash, name) "
        "VALUES (:id, :tid, :hash, 'key-a')"
    ), {"id": str(uuid.uuid4()), "tid": str(tenant_a), "hash": uuid.uuid4().hex})
    await db.execute(text(
        "INSERT INTO api_keys (id, tenant_id, key_hash, name) "
        "VALUES (:id, :tid, :hash, 'key-b')"
    ), {"id": str(uuid.uuid4()), "tid": str(tenant_b), "hash": uuid.uuid4().hex})
    await db.flush()

    # Set context to tenant A and verify isolation
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})
    result = await db.execute(text("SELECT name FROM api_keys"))
    rows = result.fetchall()
    names = [r[0] for r in rows]

    assert "key-a" in names
    assert "key-b" not in names

    await db.rollback()
