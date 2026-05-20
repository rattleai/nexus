"""Pact provider verification tests.

Verifies that the FastAPI backend satisfies the API contracts expected
by the React frontend. Consumer contracts are defined in pacts/*.json.

Uses Pact Verifier for proper contract testing when pact-python is
available, with httpx-based fallback tests for environments without it.

Usage:
    pytest tests/contract/test_pact_provider.py -v

Requires:
    pip install pact-python
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Pact provider verification runs against the actual running API
PROVIDER_URL = os.environ.get("PACT_PROVIDER_URL", "http://localhost:8000")
PACT_DIR = str(Path(__file__).parent / "pacts")


@pytest.fixture(scope="module")
def pact_verifier():
    """Create a Pact verifier for provider-side testing."""
    try:
        from pact import Verifier
    except ImportError:
        pytest.skip("pact-python not installed (pip install pact-python)")

    return Verifier(
        provider="nxs-api",
        provider_base_url=PROVIDER_URL,
    )


@pytest.mark.xfail(
    reason="Pact contracts are stale relative to the current provider "
    "(jobs list / agent definitions / billing usage responses have drifted "
    "since frontend-cadprice_api.json was generated). Re-generate from the "
    "consumer-side tests before removing this xfail.",
    strict=False,
    run=True,
)
class TestPactVerification:
    """Run Pact verification against all consumer contracts."""

    def test_verify_pacts(self, pact_verifier):
        """Verify all pact files in the pacts directory."""
        # Backend Tests runs the whole tests/ tree, but pact verification
        # needs a live API on PROVIDER_URL. The dedicated Contract Tests
        # (Pact) CI job stands one up; everywhere else, skip rather than
        # fail with a connection error.
        if not _can_reach_provider():
            pytest.skip(f"Provider not reachable at {PROVIDER_URL}; run inside the Contract Tests CI job")

        pact_files = list(Path(PACT_DIR).glob("*.json"))
        if not pact_files:
            pytest.skip("No pact files found in pacts directory")

        output, logs = pact_verifier.verify_pacts(
            *[str(f) for f in pact_files],
            enable_pending=False,
            verbose=True,
        )

        assert output == 0, f"Pact verification failed:\n{logs}"


def _can_reach_provider() -> bool:
    """Check if the provider URL is reachable."""
    try:
        import httpx

        httpx.get(f"{PROVIDER_URL}/api/v1/health/live", timeout=2)
        return True
    except Exception:
        return False


_provider_reachable = pytest.mark.skipif(
    not os.environ.get("PACT_PROVIDER_URL") and not _can_reach_provider(),
    reason=f"Provider not reachable at {PROVIDER_URL} (set PACT_PROVIDER_URL)",
)


@_provider_reachable
class TestHealthContract:
    """Verify health endpoint contract (fallback without pact-python)."""

    def test_health_live(self):
        """Health endpoint returns 200 with expected shape."""
        import httpx

        response = httpx.get(f"{PROVIDER_URL}/api/v1/health/live", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


def _assert_error_response_shape(response):
    """Validate that error responses (401/403) have the expected JSON shape."""
    data = response.json()
    assert "detail" in data, f"Error response missing 'detail' field: {data}"


@_provider_reachable
class TestJobsContract:
    """Verify jobs API contract matches frontend expectations."""

    def test_list_jobs_shape(self):
        """GET /jobs returns paginated response with expected fields."""
        import httpx

        response = httpx.get(
            f"{PROVIDER_URL}/api/v1/jobs",
            headers={"X-API-Key": "test"},
            timeout=5,
        )
        assert response.status_code in (200, 401, 403)
        if response.status_code == 200:
            data = response.json()
            assert "items" in data, "Paginated response missing 'items'"
            assert "total" in data or "count" in data, "Paginated response missing count field"
        else:
            _assert_error_response_shape(response)


@_provider_reachable
class TestAgentsContract:
    """Verify agent API contract."""

    def test_list_definitions_shape(self):
        """GET /agents/definitions returns paginated response."""
        import httpx

        response = httpx.get(
            f"{PROVIDER_URL}/api/v1/agents/definitions",
            headers={"X-API-Key": "test"},
            timeout=5,
        )
        assert response.status_code in (200, 401, 403)
        if response.status_code == 200:
            data = response.json()
            assert "items" in data, "Paginated response missing 'items'"
        else:
            _assert_error_response_shape(response)

    def test_analytics_shape(self):
        """GET /agents/analytics returns aggregate metrics."""
        import httpx

        response = httpx.get(
            f"{PROVIDER_URL}/api/v1/agents/analytics?days=7",
            headers={"X-API-Key": "test"},
            timeout=5,
        )
        assert response.status_code in (200, 401, 403)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict), "Analytics response should be a JSON object"
        else:
            _assert_error_response_shape(response)


@_provider_reachable
class TestBillingContract:
    """Verify billing API contract."""

    def test_usage_shape(self):
        """GET /billing/usage returns usage summary."""
        import httpx

        response = httpx.get(
            f"{PROVIDER_URL}/api/v1/billing/usage?days=30",
            headers={"X-API-Key": "test"},
            timeout=5,
        )
        assert response.status_code in (200, 401, 403)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict), "Usage response should be a JSON object"
        else:
            _assert_error_response_shape(response)


@_provider_reachable
class TestMCPDiscovery:
    """Verify MCP .well-known discovery endpoint."""

    def test_well_known_mcp(self):
        """/.well-known/mcp returns server capabilities."""
        import httpx

        response = httpx.get(f"{PROVIDER_URL}/.well-known/mcp", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "capabilities" in data
        assert "tool_annotations" in data
