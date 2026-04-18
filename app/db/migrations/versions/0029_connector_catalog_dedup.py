"""Connector catalog dedup: source enum + aliases column.

Adds:
    - connectorsource ENUM (yaml | composio | tenant_mcp | plugin)
    - connector_definitions.source column (server_default 'yaml')
    - connector_definitions.aliases JSONB column (nullable)

These enable the catalog sync dedup logic: normalized-slug collisions are
resolved at write time, and the marketplace query layer applies a
source-priority dedup (yaml > plugin > composio > tenant_mcp) as
defense-in-depth.

The ``source`` column defaults to ``'yaml'``, which is a safe placeholder
until the application's lifespan re-runs ``sync_builtins`` +
``sync_composio_catalog`` and correctly labels every row.

Revision ID: 0029_connector_catalog_dedup
Revises: 0028_connector_hardening
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB

revision = "0029_connector_catalog_dedup"
down_revision = "0028_connector_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create connectorsource enum ────────────────────────────────
    # Uses ``create_type=False`` + explicit ``.create(checkfirst=True)``
    # pattern matching 0027/0028 so SQLAlchemy never auto-creates the
    # type while emitting the add_column DDL.

    connector_source_enum = PG_ENUM(
        "yaml", "composio", "tenant_mcp", "plugin",
        name="connectorsource",
        create_type=False,
    )
    connector_source_enum.create(op.get_bind(), checkfirst=True)

    # ── 2. Add new columns to connector_definitions ──────────────────

    op.add_column(
        "connector_definitions",
        sa.Column(
            "source",
            connector_source_enum,
            nullable=False,
            server_default="yaml",
        ),
    )
    op.add_column(
        "connector_definitions",
        sa.Column("aliases", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_definitions", "aliases")
    op.drop_column("connector_definitions", "source")
    sa.Enum(name="connectorsource").drop(op.get_bind(), checkfirst=True)
