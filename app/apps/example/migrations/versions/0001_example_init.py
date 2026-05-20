"""Example plugin — initial (no-op) migration.

Demonstrates how a plugin contributes its own Alembic history:

* The file lives under ``app/apps/<plugin>/migrations/versions/``.
* ``down_revision`` chains into the core history; here we depend on the
  bootstrap revision ``0001_basic_schema``. When you start a new plugin,
  set ``down_revision`` to the most recent revision in your dependency
  graph (either core or another plugin you depend on).
* ``revision`` must be unique across every enabled plugin's history.

The reference plugin owns no tables, so ``upgrade()`` and ``downgrade()``
are intentionally empty. Replace them with ``op.create_table(...)`` and
its inverse when your plugin introduces models.

See ``docs/PLUGINS.md`` → "Migrations" for the full contract.
"""

from __future__ import annotations

revision = "0001_example_init"
down_revision = "0001_basic_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No schema changes — placeholder so Alembic sees the plugin's history."""


def downgrade() -> None:
    """Inverse of upgrade(); also a no-op."""
