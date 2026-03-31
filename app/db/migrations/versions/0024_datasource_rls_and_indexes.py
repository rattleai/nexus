"""Add RLS policies, missing indexes, and cascade FK fix for datasource tables.

Addresses gaps in migration 0019:
- Enable RLS on cloud_connections, data_sources, data_source_chunks, config_item_provenance
- Add CASCADE to config_item_provenance.data_source_id FK
- Add missing plain tenant_id indexes

Revision ID: 0024_datasource_rls_and_indexes
Revises: 0023_add_datasource_indexes
Create Date: 2026-03-26
"""

from alembic import op

revision = "0024_datasource_rls_and_indexes"
down_revision = "0023_add_datasource_indexes"
branch_labels = None
depends_on = None

# ── Helpers ──────────────────────────────────────────────────────────

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _rls(table: str, tenant_col: str = "tenant_id") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({tenant_col} = {TENANT_SETTING})"
    )


def _drop_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


# ── Upgrade ──────────────────────────────────────────────────────────


def upgrade() -> None:
    # 1. Enable RLS on all datasource tables
    _rls("cloud_connections")
    _rls("data_sources")
    _rls("data_source_chunks")
    _rls("config_item_provenance")

    # 2. Add missing plain tenant_id indexes (defined in ORM but missing from 0019)
    op.create_index("ix_cloud_connections_tenant", "cloud_connections", ["tenant_id"])
    op.create_index("ix_data_sources_tenant", "data_sources", ["tenant_id"])

    # 3. Fix cascade delete on config_item_provenance.data_source_id FK
    op.drop_constraint(
        "config_item_provenance_data_source_id_fkey",
        "config_item_provenance",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "config_item_provenance_data_source_id_fkey",
        "config_item_provenance",
        "data_sources",
        ["data_source_id"],
        ["id"],
        ondelete="CASCADE",
    )


# ── Downgrade ────────────────────────────────────────────────────────


def downgrade() -> None:
    # Reverse cascade FK
    op.drop_constraint(
        "config_item_provenance_data_source_id_fkey",
        "config_item_provenance",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "config_item_provenance_data_source_id_fkey",
        "config_item_provenance",
        "data_sources",
        ["data_source_id"],
        ["id"],
    )

    # Drop plain tenant indexes
    op.drop_index("ix_data_sources_tenant", table_name="data_sources")
    op.drop_index("ix_cloud_connections_tenant", table_name="cloud_connections")

    # Disable RLS
    _drop_rls("config_item_provenance")
    _drop_rls("data_source_chunks")
    _drop_rls("data_sources")
    _drop_rls("cloud_connections")
