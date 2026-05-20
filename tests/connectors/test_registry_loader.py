"""Registry YAML loader strips plaintext secrets (P0.1)."""

from __future__ import annotations

from app.connectors.registry import connector_registry


def test_strip_secrets_removes_client_credentials():
    data = {
        "slug": "test",
        "auth_config": {
            "authorize_url": "https://example.com/authorize",
            "client_id": "leaked-id",
            "client_secret": "leaked-secret",
            "scopes": ["read"],
        },
        "webhook_config": {
            "signature_header": "X-Sig",
            "secret": "leaked-webhook-secret",
        },
    }
    connector_registry._strip_secrets(data, slug="test")

    assert "client_id" not in data["auth_config"]
    assert "client_secret" not in data["auth_config"]
    assert data["auth_config"]["authorize_url"] == "https://example.com/authorize"
    assert data["auth_config"]["scopes"] == ["read"]
    assert "secret" not in data["webhook_config"]
    assert data["webhook_config"]["signature_header"] == "X-Sig"


def test_strip_secrets_handles_missing_configs():
    data = {"slug": "test"}
    connector_registry._strip_secrets(data, slug="test")
    assert data == {"slug": "test"}

    data = {"slug": "test", "auth_config": None}
    connector_registry._strip_secrets(data, slug="test")
    assert data["auth_config"] is None


def test_all_builtin_yamls_are_clean_of_secrets():
    defs = connector_registry.load_builtins()
    assert len(defs) >= 1
    for d in defs:
        auth = d.get("auth_config") or {}
        # After strip: built-ins should NEVER ship non-empty secrets
        assert not auth.get("client_id"), f"{d.get('slug')} ships a client_id"
        assert not auth.get("client_secret"), f"{d.get('slug')} ships a client_secret"
        wh = d.get("webhook_config") or {}
        assert not wh.get("secret"), f"{d.get('slug')} ships a webhook secret"
