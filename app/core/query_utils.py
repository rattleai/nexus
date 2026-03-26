"""Shared query utilities for SQLAlchemy."""


def escape_like(value: str) -> str:
    """Escape LIKE pattern metacharacters (%, _, \\).

    Use with SQLAlchemy's ``.ilike()`` / ``.like()`` and pass ``escape="\\\\"``
    to the expression so the database honours the escape sequences::

        col.ilike(f"%{escape_like(user_input)}%")
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
