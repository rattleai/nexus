"""Add CHECK constraints for cardinality bounds on characteristic_assignments.

Revision ID: 0018_cardinality_check_constraints
Revises: 0017_cardinality_constraints
Create Date: 2026-03-26
"""

from alembic import op

revision = "0018_cardinality_check_constraints"
down_revision = "0017_cardinality_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_char_assignments_min_select_gte_0",
        "characteristic_assignments",
        "min_select IS NULL OR min_select >= 0",
    )
    op.create_check_constraint(
        "ck_char_assignments_max_select_gte_1",
        "characteristic_assignments",
        "max_select IS NULL OR max_select >= 1",
    )
    op.create_check_constraint(
        "ck_char_assignments_min_lte_max",
        "characteristic_assignments",
        "min_select IS NULL OR max_select IS NULL OR min_select <= max_select",
    )


def downgrade() -> None:
    op.drop_constraint("ck_char_assignments_min_lte_max", "characteristic_assignments")
    op.drop_constraint("ck_char_assignments_max_select_gte_1", "characteristic_assignments")
    op.drop_constraint("ck_char_assignments_min_select_gte_0", "characteristic_assignments")
