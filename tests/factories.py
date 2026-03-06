"""Shared test factories for creating mock domain objects.

Centralizes object creation to reduce duplication across test modules
and ensure consistent test data.

Usage:
    from tests.factories import make_tenant, make_job, make_api_key, make_user
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.db.models import JobStatus


def make_tenant(**overrides) -> MagicMock:
    """Create a mock Tenant object."""
    defaults = {
        "id": uuid.uuid4(),
        "slug": "test-tenant",
        "plan": "free",
        "is_active": True,
        "settings": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    # 'name' is a reserved MagicMock kwarg — must be set after construction
    tenant_name = defaults.pop("name", "Test Tenant")
    mock = MagicMock(**defaults)
    mock.name = tenant_name
    return mock


def make_job(tenant_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock Job object."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id or uuid.uuid4(),
        "type": "export",
        "status": JobStatus.PENDING,
        "webhook_url": None,
        "payload": None,
        "input_hash": None,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "version": 1,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def make_api_key(tenant_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock ApiKey object."""
    tid = tenant_id or uuid.uuid4()
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tid,
        "key_hash": "fakehash" + uuid.uuid4().hex[:56],
        "rate_limit": 100,
        "scopes": ["jobs:read", "jobs:write"],
        "active": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "tenant": make_tenant(id=tid),
    }
    defaults.update(overrides)
    key_name = defaults.pop("name", "test-key")
    mock = MagicMock(**defaults)
    mock.name = key_name
    return mock


def make_user(tenant_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock User object."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id or uuid.uuid4(),
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "email_verified": True,
        "password_hash": "argon2id$fakehash",
        "display_name": "Test User",
        "is_active": True,
        "last_login_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def make_webhook_endpoint(tenant_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock WebhookEndpoint object."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id or uuid.uuid4(),
        "url": "https://example.com/webhook",
        "description": "Test webhook",
        "secret": "encrypted_secret",
        "events": ["job.completed", "job.failed"],
        "active": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(**defaults)
    mock.get_secret.return_value = "whsec_test_secret"
    return mock


def make_subscription(tenant_id: uuid.UUID | None = None, **overrides) -> MagicMock:
    """Create a mock Subscription object."""
    from app.db.models import SubscriptionStatus

    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id or uuid.uuid4(),
        "plan_id": uuid.uuid4(),
        "stripe_subscription_id": f"sub_{uuid.uuid4().hex[:24]}",
        "stripe_customer_id": f"cus_{uuid.uuid4().hex[:24]}",
        "status": SubscriptionStatus.ACTIVE,
        "current_period_start": now,
        "current_period_end": now,
        "cancel_at": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)
