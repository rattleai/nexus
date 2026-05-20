"""Tests for the CLI HTTP client."""

from app.cli.client import CLIError, NexusClient


def test_cli_error_properties():
    err = CLIError("test error", exit_code=2, hint="try again")
    assert err.message == "test error"
    assert err.exit_code == 2
    assert err.hint == "try again"


def test_nxs_client_sets_headers():
    client = NexusClient("http://localhost:8000", "test-key")
    assert client._client.headers["X-API-Key"] == "test-key"
    assert "nxs-cli" in client._client.headers["User-Agent"]
    client.close()


def test_nxs_client_strips_trailing_slash():
    client = NexusClient("http://localhost:8000/", "key")
    assert client.base_url == "http://localhost:8000"
    client.close()
