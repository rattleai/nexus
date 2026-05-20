"""Add ``created_by_user_id`` to ``data_sources`` for per-user drive ingest.

Cloud-drive extraction runs in a Celery worker, outside the HTTP request
thread that created the ``DataSource``. The worker needs the invoking
user's identity so the connector broker resolves the correct per-user
``TenantConnection`` (confused-deputy protection carried forward from PR
#63). Storing the user id on the row avoids plumbing a separate task
queue payload or re-resolving it via audit logs.

Nullable: system-created sources (seeds, migrations, tests) don't need
a synthetic user; the adapter layer falls back to "any active connection
for the tenant" when ``actor_user_id`` is None.

Revision ID: 0030_datasource_actor_user
Revises: 0029_connector_catalog_dedup
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030_datasource_actor_user"
down_revision = "0029_connector_catalog_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column(
            "created_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_data_sources_created_by_user",
        "data_sources",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_sources_created_by_user", table_name="data_sources")
    op.drop_column("data_sources", "created_by_user_id")
