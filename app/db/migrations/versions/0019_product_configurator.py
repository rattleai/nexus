"""Product configurator, configurable BOM, and pricing models.

Revision ID: 0019_product_configurator
Revises: 0018_fix_session_fk_cascade
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0019_product_configurator"
down_revision = "0018_fix_session_fk_cascade"
branch_labels = None
depends_on = None

# ── Helpers ──────────────────────────────────────────────────────────

TENANT_SETTING = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _create_enum(name: str, values: list[str]) -> None:
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": name},
    )
    if result.scalar() is None:
        val_list = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({val_list})")


def _rls(table: str, tenant_col: str = "tenant_id") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({tenant_col} = {TENANT_SETTING})"
    )


# ── Upgrade ──────────────────────────────────────────────────────────


def upgrade() -> None:
    # NOTE: Enum types are created automatically by sa.Enum() in op.create_table()
    # The _create_enum helper was removed because sa.Enum auto-creation handles it.
    _noop = [  # noqa: F841 - keep for downgrade reference
        ("productstatus", ["draft", "active", "deprecated", "archived"]),
        ("characteristictype", ["enum", "numeric", "boolean", "text"]),
        ("constrainttype", [
            "requires", "excludes", "selection_condition",
            "default_value", "formula", "table",
        ]),
        ("bomitemtype", ["component", "sub_assembly", "phantom", "reference"]),
        ("configurationstatus", ["in_progress", "complete", "invalid", "locked"]),
        ("pricingruletype", [
            "base_price", "option_surcharge", "volume_discount",
            "conditional", "formula", "tiered", "margin",
        ]),
    ]

    # ── product_families ─────────────────────────────────────────────
    op.create_table(
        "product_families",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        # SoftDeleteMixin
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # AuditMixin
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        # VersionMixin
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        # TimestampMixin
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_family_slug", "product_families", ["tenant_id", "slug"])
    op.create_index("ix_product_families_tenant", "product_families", ["tenant_id"])
    op.create_index("ix_product_families_deleted_at", "product_families", ["deleted_at"])
    _rls("product_families")

    # ── products ─────────────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("product_families.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("sku_prefix", sa.String(50), nullable=True),
        sa.Column("status", sa.Enum("draft", "active", "deprecated", "archived", name="productstatus"), nullable=False, server_default="draft"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_slug", "products", ["tenant_id", "slug"])
    op.create_index("ix_products_tenant_status", "products", ["tenant_id", "status"])
    op.create_index("ix_products_family_id", "products", ["family_id"])
    op.create_index("ix_products_deleted_at", "products", ["deleted_at"])
    _rls("products")

    # ── product_versions ─────────────────────────────────────────────
    op.create_table(
        "product_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="false"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_version_number", "product_versions", ["product_id", "version_number"])
    op.create_index("ix_product_versions_product_active", "product_versions", ["product_id", "is_active"])
    op.create_index("ix_product_versions_tenant_id", "product_versions", ["tenant_id"])
    _rls("product_versions")

    # ── characteristic_groups ────────────────────────────────────────
    op.create_table(
        "characteristic_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_char_group_slug", "characteristic_groups", ["tenant_id", "slug"])
    op.create_index("ix_characteristic_groups_tenant_id", "characteristic_groups", ["tenant_id"])
    op.create_index("ix_characteristic_groups_deleted_at", "characteristic_groups", ["deleted_at"])
    _rls("characteristic_groups")

    # ── characteristics ──────────────────────────────────────────────
    op.create_table(
        "characteristics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("characteristic_groups.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("char_type", sa.Enum("enum", "numeric", "boolean", "text", name="characteristictype"), nullable=False),
        sa.Column("numeric_min", sa.Float, nullable=True),
        sa.Column("numeric_max", sa.Float, nullable=True),
        sa.Column("numeric_step", sa.Float, nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("is_required", sa.Boolean, server_default="false"),
        sa.Column("is_multi_select", sa.Boolean, server_default="false"),
        sa.Column("default_value", sa.String(500), nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_characteristic_slug", "characteristics", ["tenant_id", "slug"])
    op.create_index("ix_characteristics_tenant_group", "characteristics", ["tenant_id", "group_id"])
    op.create_index("ix_characteristics_deleted_at", "characteristics", ["deleted_at"])
    _rls("characteristics")

    # ── characteristic_values ────────────────────────────────────────
    op.create_table(
        "characteristic_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("characteristic_id", UUID(as_uuid=True), sa.ForeignKey("characteristics.id"), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("price_adjustment", sa.Numeric(12, 4), nullable=True),
        sa.Column("image_url", sa.String(2048), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_char_value", "characteristic_values", ["characteristic_id", "value"])
    op.create_index("ix_char_values_characteristic", "characteristic_values", ["characteristic_id"])
    op.create_index("ix_characteristic_values_tenant_id", "characteristic_values", ["tenant_id"])
    _rls("characteristic_values")

    # ── characteristic_assignments ───────────────────────────────────
    op.create_table(
        "characteristic_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("characteristic_id", UUID(as_uuid=True), sa.ForeignKey("characteristics.id"), nullable=False),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("is_required", sa.Boolean, nullable=True),
        sa.Column("default_value", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_product_characteristic", "characteristic_assignments", ["product_id", "characteristic_id"])
    op.create_index("ix_char_assignments_product", "characteristic_assignments", ["product_id"])
    op.create_index("ix_characteristic_assignments_tenant_id", "characteristic_assignments", ["tenant_id"])
    _rls("characteristic_assignments")

    # ── constraint_groups ────────────────────────────────────────────
    op.create_table(
        "constraint_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_constraint_groups_product", "constraint_groups", ["product_id"])
    op.create_index("ix_constraint_groups_tenant_id", "constraint_groups", ["tenant_id"])
    op.create_index("ix_constraint_groups_deleted_at", "constraint_groups", ["deleted_at"])
    _rls("constraint_groups")

    # ── constraint_rules ─────────────────────────────────────────────
    op.create_table(
        "constraint_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("constraint_groups.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("constraint_type", sa.Enum("requires", "excludes", "selection_condition", "default_value", "formula", "table", name="constrainttype"), nullable=False),
        sa.Column("expression", JSONB, nullable=False),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_constraint_rules_product", "constraint_rules", ["product_id"])
    op.create_index("ix_constraint_rules_product_type", "constraint_rules", ["product_id", "constraint_type"])
    op.create_index("ix_constraint_rules_tenant_id", "constraint_rules", ["tenant_id"])
    op.create_index("ix_constraint_rules_deleted_at", "constraint_rules", ["deleted_at"])
    _rls("constraint_rules")

    # ── variant_tables ───────────────────────────────────────────────
    op.create_table(
        "variant_tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("columns", JSONB, nullable=False),
        sa.Column("rows", JSONB, nullable=False),
        sa.Column("input_columns", JSONB, nullable=False),
        sa.Column("output_columns", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_variant_tables_product", "variant_tables", ["product_id"])
    op.create_index("ix_variant_tables_tenant_id", "variant_tables", ["tenant_id"])
    _rls("variant_tables")

    # ── product_media ────────────────────────────────────────────────
    op.create_table(
        "product_media",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(50), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("display_order", sa.Integer, server_default="0"),
        sa.Column("alt_text", sa.String(500), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_media_entity", "product_media", ["entity_type", "entity_id"])
    op.create_index("ix_product_media_tenant", "product_media", ["tenant_id"])
    _rls("product_media")

    # ── bom_headers ──────────────────────────────────────────────────
    op.create_table(
        "bom_headers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("bom_type", sa.String(50), server_default="manufacturing"),
        sa.Column("is_primary", sa.Boolean, server_default="false"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bom_headers_product", "bom_headers", ["product_id"])
    op.create_index("ix_bom_headers_tenant_product", "bom_headers", ["tenant_id", "product_id"])
    op.create_index("ix_bom_headers_deleted_at", "bom_headers", ["deleted_at"])
    _rls("bom_headers")

    # ── bom_items ────────────────────────────────────────────────────
    op.create_table(
        "bom_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("bom_header_id", UUID(as_uuid=True), sa.ForeignKey("bom_headers.id"), nullable=False),
        sa.Column("parent_item_id", UUID(as_uuid=True), sa.ForeignKey("bom_items.id"), nullable=True),
        sa.Column("item_type", sa.Enum("component", "sub_assembly", "phantom", "reference", name="bomitemtype"), server_default="component"),
        sa.Column("part_number", sa.String(100), nullable=False),
        sa.Column("part_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("quantity", sa.Numeric(12, 4), server_default="1.0000"),
        sa.Column("quantity_expression", JSONB, nullable=True),
        sa.Column("unit_of_measure", sa.String(20), server_default="EA"),
        sa.Column("sub_product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("selection_condition", JSONB, nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_optional", sa.Boolean, server_default="false"),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bom_items_header", "bom_items", ["bom_header_id"])
    op.create_index("ix_bom_items_part_number", "bom_items", ["tenant_id", "part_number"])
    op.create_index("ix_bom_items_parent_item_id", "bom_items", ["parent_item_id"])
    op.create_index("ix_bom_items_sub_product_id", "bom_items", ["sub_product_id"])
    op.create_index("ix_bom_items_deleted_at", "bom_items", ["deleted_at"])
    _rls("bom_items")

    # ── configuration_templates (before sessions, FK dependency) ─────
    op.create_table(
        "configuration_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_partial", sa.Boolean, server_default="true"),
        sa.Column("is_public", sa.Boolean, server_default="false"),
        sa.Column("selections", JSONB, nullable=False, server_default="[]"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_templates_tenant_product", "configuration_templates", ["tenant_id", "product_id"])
    _rls("configuration_templates")

    # ── configuration_sessions ───────────────────────────────────────
    op.create_table(
        "configuration_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("product_version_id", UUID(as_uuid=True), sa.ForeignKey("product_versions.id"), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.Enum("in_progress", "complete", "invalid", "locked", name="configurationstatus"), server_default="in_progress"),
        sa.Column("is_valid", sa.Boolean, server_default="false"),
        sa.Column("is_complete", sa.Boolean, server_default="false"),
        sa.Column("validation_errors", JSONB, nullable=True),
        sa.Column("available_domains", JSONB, nullable=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("configuration_templates.id"), nullable=True),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_sessions_tenant_product", "configuration_sessions", ["tenant_id", "product_id"])
    op.create_index("ix_config_sessions_user", "configuration_sessions", ["user_id"])
    op.create_index("ix_config_sessions_status", "configuration_sessions", ["tenant_id", "status"])
    _rls("configuration_sessions")

    # ── configuration_selections ─────────────────────────────────────
    op.create_table(
        "configuration_selections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("configuration_sessions.id"), nullable=False),
        sa.Column("characteristic_id", UUID(as_uuid=True), sa.ForeignKey("characteristics.id"), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("is_auto_set", sa.Boolean, server_default="false"),
        sa.Column("set_by_rule_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_selections_session", "configuration_selections", ["session_id"])
    op.create_index("ix_config_selections_session_char", "configuration_selections", ["session_id", "characteristic_id"])
    op.create_index("ix_configuration_selections_tenant_id", "configuration_selections", ["tenant_id"])
    _rls("configuration_selections")

    # ── configured_boms ──────────────────────────────────────────────
    op.create_table(
        "configured_boms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("configuration_sessions.id"), nullable=False, unique=True),
        sa.Column("bom_header_id", UUID(as_uuid=True), sa.ForeignKey("bom_headers.id"), nullable=False),
        sa.Column("resolved_items", JSONB, nullable=False),
        sa.Column("total_components", sa.Integer, server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("selection_snapshot", JSONB, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolution_duration_ms", sa.Integer, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_configured_boms_tenant", "configured_boms", ["tenant_id"])
    op.create_index("ix_configured_boms_session", "configured_boms", ["session_id"])
    _rls("configured_boms")

    # ── pricing_rules ────────────────────────────────────────────────
    op.create_table(
        "pricing_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rule_type", sa.Enum("base_price", "option_surcharge", "volume_discount", "conditional", "formula", "tiered", "margin", name="pricingruletype"), nullable=False),
        sa.Column("expression", JSONB, nullable=False),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(3), server_default="EUR"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pricing_rules_product", "pricing_rules", ["product_id"])
    op.create_index("ix_pricing_rules_product_type", "pricing_rules", ["product_id", "rule_type"])
    op.create_index("ix_pricing_rules_tenant_id", "pricing_rules", ["tenant_id"])
    op.create_index("ix_pricing_rules_deleted_at", "pricing_rules", ["deleted_at"])
    _rls("pricing_rules")

    # ── configuration_pricing ────────────────────────────────────────
    op.create_table(
        "configuration_pricing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("configuration_sessions.id"), nullable=False, unique=True),
        sa.Column("currency", sa.String(3), server_default="EUR"),
        sa.Column("base_price", sa.Numeric(14, 4), server_default="0"),
        sa.Column("total_adjustments", sa.Numeric(14, 4), server_default="0"),
        sa.Column("final_price", sa.Numeric(14, 4), server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 4), server_default="0"),
        sa.Column("margin_amount", sa.Numeric(14, 4), server_default="0"),
        sa.Column("margin_percentage", sa.Numeric(8, 4), server_default="0"),
        sa.Column("price_breakdown", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_profitable", sa.Boolean, server_default="false"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_config_pricing_tenant", "configuration_pricing", ["tenant_id"])
    op.create_index("ix_config_pricing_session", "configuration_pricing", ["session_id"])
    _rls("configuration_pricing")


# ── Downgrade ────────────────────────────────────────────────────────


def downgrade() -> None:
    tables = [
        "configuration_pricing",
        "configured_boms",
        "configuration_selections",
        "configuration_sessions",
        "configuration_templates",
        "pricing_rules",
        "bom_items",
        "bom_headers",
        "product_media",
        "variant_tables",
        "constraint_rules",
        "constraint_groups",
        "characteristic_assignments",
        "characteristic_values",
        "characteristics",
        "characteristic_groups",
        "product_versions",
        "products",
        "product_families",
    ]
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)

    for enum_name in [
        "pricingruletype", "configurationstatus", "bomitemtype",
        "constrainttype", "characteristictype", "productstatus",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
