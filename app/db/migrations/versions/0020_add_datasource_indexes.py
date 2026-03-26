"""Add missing indexes on data source tables.

Adds an index on data_sources.cloud_connection_id to speed up joins
and lookups by cloud connection.

Revision ID: 0020_add_datasource_indexes
Revises: 0019_datasource_models
Create Date: 2026-03-26
"""

from alembic import op

revision = "0020_add_datasource_indexes"
down_revision = "0019_datasource_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_data_sources_cloud_connection_id",
        "data_sources",
        ["cloud_connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_sources_cloud_connection_id", table_name="data_sources")
