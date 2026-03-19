"""Enforce audit_log immutability at the database level.

Adds a trigger that prevents UPDATE/DELETE on audit_logs and revokes
those permissions from app_user. A GUC bypass (app.audit_purge_enabled)
allows privileged compliance-mandated purge operations.

Revision ID: 0008_audit_log_immutability
Revises: 0007_rls_with_check
Create Date: 2026-03-19
"""

from alembic import op

revision = "0008_audit_log_immutability"
down_revision = "0007_rls_with_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create trigger function that blocks UPDATE/DELETE unless GUC bypass is set
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Allow privileged purge operations via GUC bypass
            IF current_setting('app.audit_purge_enabled', true) = 'true' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_logs table is immutable: % operations are not allowed',
                TG_OP
                USING HINT = 'Set app.audit_purge_enabled=true for compliance-mandated purge';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach trigger BEFORE UPDATE OR DELETE
    op.execute("""
        CREATE TRIGGER audit_log_immutability_trigger
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
    """)

    # Defense-in-depth: revoke UPDATE/DELETE from app_user
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM app_user")


def downgrade() -> None:
    # Restore permissions
    op.execute("GRANT UPDATE, DELETE ON audit_logs TO app_user")

    # Remove trigger and function
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutability_trigger ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
