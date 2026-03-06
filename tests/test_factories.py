"""Tests for test factories — ensures factories produce valid mock objects."""

from tests.factories import (
    make_api_key,
    make_job,
    make_subscription,
    make_tenant,
    make_user,
    make_webhook_endpoint,
)


def test_make_tenant_defaults():
    tenant = make_tenant()
    assert tenant.name == "Test Tenant"
    assert tenant.slug == "test-tenant"
    assert tenant.plan == "free"
    assert tenant.is_active is True
    assert tenant.id is not None


def test_make_tenant_overrides():
    tenant = make_tenant(name="Custom", plan="pro")
    assert tenant.name == "Custom"
    assert tenant.plan == "pro"


def test_make_job_defaults():
    job = make_job()
    assert job.type == "export"
    assert job.status.value == "pending"
    assert job.version == 1


def test_make_api_key_defaults():
    key = make_api_key()
    assert key.active is True
    assert "jobs:read" in key.scopes
    assert key.tenant is not None


def test_make_user_defaults():
    user = make_user()
    assert user.is_active is True
    assert "@example.com" in user.email


def test_make_webhook_endpoint_defaults():
    endpoint = make_webhook_endpoint()
    assert endpoint.active is True
    assert "job.completed" in endpoint.events
    assert endpoint.get_secret() == "whsec_test_secret"


def test_make_subscription_defaults():
    sub = make_subscription()
    assert sub.status.value == "active"
    assert sub.stripe_subscription_id.startswith("sub_")
