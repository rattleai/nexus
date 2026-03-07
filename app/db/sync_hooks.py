"""ORM event listeners for populating the ChangeLog on syncable entity changes.

Listens to SQLAlchemy after_flush events and records create/update/delete
operations for any model that uses SyncMixin. Mobile clients pull these
records via the /sync/changes endpoint.

Usage: call ``register_sync_hooks()`` once at startup (in lifespan).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import structlog
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import instance_state

from app.db.models.mobile import ChangeLog, SyncMixin

logger = structlog.stdlib.get_logger()

# Map model class names to entity_type strings
_ENTITY_TYPE_MAP: dict[str, str] = {
    "Job": "job",
    "Notification": "notification",
}

_SYNC_HOOKS_IN_FLUSH_KEY = "_sync_hooks_in_flush"


def _get_entity_type(instance: Any) -> str | None:
    """Return the sync entity type for a model instance, or None if not syncable."""
    if isinstance(instance, ChangeLog):
        return None  # Explicit guard: never track ChangeLog itself
    if not isinstance(instance, SyncMixin):
        return None
    cls_name = type(instance).__name__
    return _ENTITY_TYPE_MAP.get(cls_name)


def _get_tenant_id(instance: Any) -> uuid.UUID | None:
    """Extract tenant_id from a model instance."""
    return getattr(instance, "tenant_id", None)


def _get_changed_fields(instance: Any) -> dict[str, Any] | None:
    """Return dict of changed column names and their new values.

    Only iterates over column attributes (not relationships) to avoid
    serializing ORM model instances.
    """
    mapper = inspect(type(instance))
    state = instance_state(instance)
    changes = {}
    for attr in mapper.column_attrs:
        hist = state.attrs[attr.key].history
        if hist.has_changes():
            value = getattr(instance, attr.key, None)
            if isinstance(value, uuid.UUID):
                value = str(value)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            changes[attr.key] = value
    return changes if changes else None


def _compute_checksum(instance: Any) -> str:
    """Compute a deterministic checksum for a syncable entity's current state.

    Only includes column attributes (not relationships) for deterministic output.
    """
    mapper = inspect(type(instance))
    data = {}
    for attr in mapper.column_attrs:
        if attr.key in ("sync_version", "sync_checksum", "created_at", "updated_at"):
            continue
        value = getattr(instance, attr.key, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        data[attr.key] = value
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _after_flush(session: Session, flush_context: Any) -> None:
    """After flush handler: record changes for syncable entities."""
    # Session-local re-entrancy guard (safe under concurrent async requests)
    if session.info.get(_SYNC_HOOKS_IN_FLUSH_KEY):
        return
    session.info[_SYNC_HOOKS_IN_FLUSH_KEY] = True

    try:
        changes_to_add: list[ChangeLog] = []

        # Process new objects
        for instance in list(session.new):
            entity_type = _get_entity_type(instance)
            if not entity_type:
                continue
            tenant_id = _get_tenant_id(instance)
            if not tenant_id:
                continue

            entity_id = getattr(instance, "id", None)
            if not entity_id:
                continue

            changes_to_add.append(ChangeLog(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                operation="create",
                changed_fields=None,
            ))

            instance.sync_checksum = _compute_checksum(instance)

        # Process dirty (updated) objects
        for instance in list(session.dirty):
            entity_type = _get_entity_type(instance)
            if not entity_type:
                continue
            tenant_id = _get_tenant_id(instance)
            if not tenant_id:
                continue

            entity_id = getattr(instance, "id", None)
            if not entity_id:
                continue

            changed_fields = _get_changed_fields(instance)
            if not changed_fields:
                continue

            changes_to_add.append(ChangeLog(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                operation="update",
                changed_fields=changed_fields,
            ))

            instance.sync_checksum = _compute_checksum(instance)

        # Process deleted objects
        for instance in list(session.deleted):
            entity_type = _get_entity_type(instance)
            if not entity_type:
                continue
            tenant_id = _get_tenant_id(instance)
            if not tenant_id:
                continue

            entity_id = getattr(instance, "id", None)
            if not entity_id:
                continue

            changes_to_add.append(ChangeLog(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                operation="delete",
                changed_fields=None,
            ))

        if changes_to_add:
            for cl in changes_to_add:
                session.add(cl)
            logger.debug("sync_changelog_recorded", count=len(changes_to_add))
    finally:
        session.info[_SYNC_HOOKS_IN_FLUSH_KEY] = False


def register_sync_hooks() -> None:
    """Register ORM event listeners for sync change tracking.

    Listens on the Session class globally so all sessions (sync and async)
    automatically record changes for syncable entities.
    """
    event.listen(Session, "after_flush", _after_flush)
    logger.info("sync_hooks_registered")
