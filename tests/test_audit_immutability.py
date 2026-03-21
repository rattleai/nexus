"""Tests for audit_log immutability (migration 0008).

Verifies that the trigger prevents UPDATE/DELETE on audit_logs
and that the GUC bypass works for compliance-mandated purge.

Requires a real PostgreSQL database with migrations applied.
Run with: DATABASE_URL=... pytest -m integration tests/test_audit_immutability.py
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
async def test_audit_log_update_blocked(db: AsyncSession):
    """UPDATE on audit_logs should be rejected by the trigger."""
    log_id = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO audit_logs (id, action, resource_type) "
        "VALUES (:id, 'CREATE', 'test')"
    ), {"id": str(log_id)})
    await db.flush()

    with pytest.raises(Exception, match="immutable"):
        await db.execute(text(
            "UPDATE audit_logs SET action = 'MODIFIED' WHERE id = :id"
        ), {"id": str(log_id)})

    await db.rollback()


@pytest.mark.asyncio
async def test_audit_log_delete_blocked(db: AsyncSession):
    """DELETE on audit_logs should be rejected by the trigger."""
    log_id = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO audit_logs (id, action, resource_type) "
        "VALUES (:id, 'CREATE', 'test')"
    ), {"id": str(log_id)})
    await db.flush()

    with pytest.raises(Exception, match="immutable"):
        await db.execute(text(
            "DELETE FROM audit_logs WHERE id = :id"
        ), {"id": str(log_id)})

    await db.rollback()


@pytest.mark.asyncio
async def test_audit_log_insert_allowed(db: AsyncSession):
    """INSERT on audit_logs should still work (append-only)."""
    log_id = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO audit_logs (id, action, resource_type) "
        "VALUES (:id, 'CREATE', 'test')"
    ), {"id": str(log_id)})

    result = await db.execute(text(
        "SELECT action FROM audit_logs WHERE id = :id"
    ), {"id": str(log_id)})
    row = result.fetchone()
    assert row is not None
    assert row[0] == "CREATE"

    await db.rollback()


@pytest.mark.asyncio
async def test_audit_log_purge_bypass(db: AsyncSession):
    """GUC bypass should allow DELETE for compliance-mandated purge."""
    log_id = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO audit_logs (id, action, resource_type) "
        "VALUES (:id, 'CREATE', 'test')"
    ), {"id": str(log_id)})
    await db.flush()

    # Enable the bypass
    await db.execute(text("SELECT set_config('app.audit_purge_enabled', 'true', true)"))

    # DELETE should now succeed
    await db.execute(text(
        "DELETE FROM audit_logs WHERE id = :id"
    ), {"id": str(log_id)})

    result = await db.execute(text(
        "SELECT id FROM audit_logs WHERE id = :id"
    ), {"id": str(log_id)})
    assert result.fetchone() is None

    # Reset the bypass
    await db.execute(text("SELECT set_config('app.audit_purge_enabled', 'false', true)"))
    await db.rollback()
