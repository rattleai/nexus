"""Tests for the capability-based agent privilege system."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import (
    CapabilityError,
    CapabilityManager,
    CapabilityScope,
    CapabilityToken,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_manager() -> CapabilityManager:
    """Create a CapabilityManager with a deterministic signing key."""
    with patch.object(CapabilityManager, "_derive_signing_key", return_value=b"test-key-32-bytes-for-hmac-sign!"):
        return CapabilityManager()


def _make_token(
    manager: CapabilityManager,
    *,
    scope: CapabilityScope | None = None,
    ttl: int = 3600,
) -> CapabilityToken:
    return manager.create_token(
        instance_id="inst-1",
        tenant_id="tenant-1",
        agent_id="agent-1",
        scope=scope or CapabilityScope(),
        ttl_seconds=ttl,
    )


# ── TestCapabilityAttenuation ────────────────────────────────────────


class TestCapabilityAttenuation:
    """Scope.attenuate() produces the intersection / most-restrictive result."""

    def test_tools_intersection(self):
        parent = CapabilityScope(tools=["a", "b"])
        child = CapabilityScope(tools=["b", "c"])
        result = parent.attenuate(child)
        assert result.tools == ["b"]

    def test_tools_parent_only(self):
        parent = CapabilityScope(tools=["a", "b"])
        child = CapabilityScope(tools=[])
        result = parent.attenuate(child)
        assert result.tools == ["a", "b"]

    def test_tools_child_only(self):
        parent = CapabilityScope(tools=[])
        child = CapabilityScope(tools=["b", "c"])
        result = parent.attenuate(child)
        assert result.tools == ["b", "c"]

    def test_spend_minimum(self):
        parent = CapabilityScope(max_spend_usd=50.0)
        child = CapabilityScope(max_spend_usd=100.0)
        result = parent.attenuate(child)
        assert result.max_spend_usd == 50.0

    def test_spend_both_unlimited(self):
        parent = CapabilityScope(max_spend_usd=0.0)
        child = CapabilityScope(max_spend_usd=0.0)
        result = parent.attenuate(child)
        assert result.max_spend_usd == 0.0

    def test_spend_parent_limited_child_unlimited(self):
        parent = CapabilityScope(max_spend_usd=50.0)
        child = CapabilityScope(max_spend_usd=0.0)
        result = parent.attenuate(child)
        assert result.max_spend_usd == 50.0

    def test_spend_parent_unlimited_child_limited(self):
        parent = CapabilityScope(max_spend_usd=0.0)
        child = CapabilityScope(max_spend_usd=100.0)
        result = parent.attenuate(child)
        assert result.max_spend_usd == 100.0

    def test_classification_most_restrictive(self):
        parent = CapabilityScope(max_data_classification="CONFIDENTIAL")
        child = CapabilityScope(max_data_classification="RESTRICTED")
        result = parent.attenuate(child)
        # CONFIDENTIAL (index 2) < RESTRICTED (index 3) → min wins
        assert result.max_data_classification == "CONFIDENTIAL"

    def test_delegate_requires_both(self):
        parent = CapabilityScope(can_delegate=True)
        child = CapabilityScope(can_delegate=False)
        result = parent.attenuate(child)
        assert result.can_delegate is False

    def test_external_requires_both(self):
        parent = CapabilityScope(can_access_external_tools=True)
        child = CapabilityScope(can_access_external_tools=False)
        result = parent.attenuate(child)
        assert result.can_access_external_tools is False


# ── TestTokenCreation ────────────────────────────────────────────────


class TestTokenCreation:
    """CapabilityManager.create_token produces well-formed tokens."""

    def test_token_fields(self):
        manager = _make_manager()
        token = _make_token(manager)

        assert token.token_id  # non-empty
        assert token.instance_id == "inst-1"
        assert token.tenant_id == "tenant-1"
        assert token.agent_id == "agent-1"
        assert token.issued_at > 0
        assert token.expires_at > token.issued_at
        assert token.signature  # non-empty
        # token_id should be hex (uuid4().hex)
        int(token.token_id, 16)

    def test_valid_signature(self):
        manager = _make_manager()
        token = _make_token(manager)
        assert manager.verify_token(token) is True

    def test_custom_ttl(self):
        manager = _make_manager()
        token = _make_token(manager, ttl=60)
        # expires_at should be ~60s after issued_at
        assert abs((token.expires_at - token.issued_at) - 60) < 1


# ── TestTokenVerification ────────────────────────────────────────────


class TestTokenVerification:
    """CapabilityManager.verify_token and related access checks."""

    def test_valid_token(self):
        manager = _make_manager()
        token = _make_token(manager)
        assert manager.verify_token(token) is True

    def test_expired_token(self):
        manager = _make_manager()
        token = _make_token(manager, ttl=1)
        token.expires_at = time.time() - 100
        assert manager.verify_token(token) is False

    def test_tampered_signature(self):
        manager = _make_manager()
        token = _make_token(manager)
        token.signature = "tampered"
        assert manager.verify_token(token) is False

    def test_missing_signature(self):
        manager = _make_manager()
        token = _make_token(manager)
        token.signature = ""
        assert manager.verify_token(token) is False

    def test_tool_access_allowed(self):
        manager = _make_manager()
        scope = CapabilityScope(tools=["ai_complete"])
        token = _make_token(manager, scope=scope)
        assert manager.verify_tool_access(token, "ai_complete") is True

    def test_tool_access_denied(self):
        manager = _make_manager()
        scope = CapabilityScope(tools=["ai_complete"])
        token = _make_token(manager, scope=scope)
        assert manager.verify_tool_access(token, "delete_all") is False

    def test_empty_tools_allows_all(self):
        manager = _make_manager()
        scope = CapabilityScope(tools=[])
        token = _make_token(manager, scope=scope)
        assert manager.verify_tool_access(token, "anything") is True

    def test_data_classification_allowed(self):
        manager = _make_manager()
        scope = CapabilityScope(max_data_classification="CONFIDENTIAL")
        token = _make_token(manager, scope=scope)
        assert manager.verify_data_classification(token, "INTERNAL") is True

    def test_data_classification_denied(self):
        manager = _make_manager()
        scope = CapabilityScope(max_data_classification="INTERNAL")
        token = _make_token(manager, scope=scope)
        assert manager.verify_data_classification(token, "CONFIDENTIAL") is False


# ── TestAttenuatedToken ──────────────────────────────────────────────


class TestAttenuatedToken:
    """CapabilityManager.create_attenuated_token for sub-agent delegation."""

    def test_attenuation_reduces_scope(self):
        manager = _make_manager()
        parent_scope = CapabilityScope(tools=["a", "b", "c"], can_delegate=True)
        parent = _make_token(manager, scope=parent_scope)

        child_scope = CapabilityScope(tools=["b", "d"])
        child = manager.create_attenuated_token(
            parent,
            child_instance_id="child-1",
            child_agent_id="agent-child",
            requested_scope=child_scope,
        )
        assert child.scope.tools == ["b"]

    def test_parent_ttl_caps_child(self):
        manager = _make_manager()
        parent_scope = CapabilityScope(can_delegate=True)
        parent = _make_token(manager, scope=parent_scope, ttl=100)

        child = manager.create_attenuated_token(
            parent,
            child_instance_id="child-1",
            child_agent_id="agent-child",
            requested_scope=CapabilityScope(),
            ttl_seconds=200,
        )
        # Child TTL should not exceed parent's remaining lifetime (~100s)
        child_ttl = child.expires_at - child.issued_at
        assert child_ttl <= 101  # small margin for execution time

    def test_invalid_parent_raises(self):
        manager = _make_manager()
        parent = _make_token(manager)
        parent.signature = "bad-signature"

        with pytest.raises(CapabilityError, match="invalid or expired"):
            manager.create_attenuated_token(
                parent,
                child_instance_id="child-1",
                child_agent_id="agent-child",
                requested_scope=CapabilityScope(),
            )

    def test_no_delegation_raises(self):
        manager = _make_manager()
        parent_scope = CapabilityScope(can_delegate=False)
        parent = _make_token(manager, scope=parent_scope)

        with pytest.raises(CapabilityError, match="does not allow delegation"):
            manager.create_attenuated_token(
                parent,
                child_instance_id="child-1",
                child_agent_id="agent-child",
                requested_scope=CapabilityScope(),
            )


# ── TestConfusedDeputyAttacks ────────────────────────────────────────


class TestConfusedDeputyAttacks:
    """Attack simulations: confused deputy, replay, and escalation."""

    def test_forged_token(self):
        """Manually constructed token with wrong signature is rejected."""
        manager = _make_manager()
        forged = CapabilityToken(
            token_id="deadbeef",
            instance_id="inst-1",
            tenant_id="tenant-1",
            agent_id="agent-1",
            scope=CapabilityScope(tools=["ai_complete"]),
            issued_at=time.time(),
            expires_at=time.time() + 3600,
            signature="forged-signature-value",
        )
        assert manager.verify_token(forged) is False

    def test_expired_replay(self):
        """Token replayed after expiry is rejected."""
        manager = _make_manager()
        token = _make_token(manager)
        token.expires_at = time.time() - 100
        assert manager.verify_token(token) is False

    def test_scope_escalation(self):
        """Modifying scope after signing invalidates the token."""
        manager = _make_manager()
        scope = CapabilityScope(tools=["ai_complete"])
        token = _make_token(manager, scope=scope)

        # Attacker tries to escalate tools
        token.scope.tools.append("admin_delete")

        # Signature now mismatches because the scope changed
        assert manager.verify_token(token) is False


# ── TestHKDFKeyDerivation ────────────────────────────────────────────


class TestHKDFKeyDerivation:
    """HKDF key derivation produces deterministic output and proper domain separation."""

    def test_deterministic_output(self):
        """Same inputs produce the same derived key."""
        key1 = CapabilityManager._derive_signing_key(version=1)
        key2 = CapabilityManager._derive_signing_key(version=1)
        assert key1 == key2

    def test_different_versions_different_keys(self):
        """Different key versions produce different derived keys."""
        key1 = CapabilityManager._derive_signing_key(version=1)
        key2 = CapabilityManager._derive_signing_key(version=2)
        assert key1 != key2


# ── TestTokenRevocation ──────────────────────────────────────────────


class TestTokenRevocation:
    """Token revocation via Redis and fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_revoked_token_detected(self):
        """Revoked token fails is_revoked check."""
        mock_redis = MagicMock()
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=[1, True])
        mock_redis.pipeline.return_value = pipeline
        mock_redis.sismember = AsyncMock(return_value=True)

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager)
            is_revoked = await manager.is_revoked(token)

        assert is_revoked is True

    @pytest.mark.asyncio
    async def test_fail_closed_on_redis_failure(self):
        """Redis failure during revocation check returns True (fail-closed)."""
        mock_redis = MagicMock()
        mock_redis.sismember = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager)
            is_revoked = await manager.is_revoked(token)

        assert is_revoked is True

    @pytest.mark.asyncio
    async def test_non_revoked_token(self):
        """Non-revoked token returns False."""
        mock_redis = MagicMock()
        mock_redis.sismember = AsyncMock(return_value=False)

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager)
            is_revoked = await manager.is_revoked(token)

        assert is_revoked is False


# ── TestVerifyTokenFull ──────────────────────────────────────────────


class TestVerifyTokenFull:
    """verify_token_full combines signature + expiry + revocation check."""

    @pytest.mark.asyncio
    async def test_valid_non_revoked_token(self):
        """Valid, non-revoked token passes full verification."""
        mock_redis = MagicMock()
        mock_redis.sismember = AsyncMock(return_value=False)

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager)
            result = await manager.verify_token_full(token)

        assert result is True

    @pytest.mark.asyncio
    async def test_valid_but_revoked_token(self):
        """Valid token that has been revoked fails full verification."""
        mock_redis = MagicMock()
        mock_redis.sismember = AsyncMock(return_value=True)

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager)
            result = await manager.verify_token_full(token)

        assert result is False

    @pytest.mark.asyncio
    async def test_expired_token_fails_without_revocation_check(self):
        """Expired token fails full verification before revocation is even checked."""
        mock_redis = MagicMock()
        mock_redis.sismember = AsyncMock(return_value=False)

        with patch("app.agents.capabilities.redis_pool", mock_redis):
            manager = _make_manager()
            token = _make_token(manager, ttl=1)
            token.expires_at = time.time() - 100
            result = await manager.verify_token_full(token)

        assert result is False
        # sismember should NOT have been called since signature check failed first
        mock_redis.sismember.assert_not_called()


# ── TestKeyRotation ──────────────────────────────────────────────────


class TestKeyRotation:
    """Token signed with previous key version still verifies during rotation grace period."""

    def test_previous_key_version_verifies(self):
        """Token signed with old key version verifies when current version is bumped."""
        # Create a manager that simulates key version 2 being current,
        # with version 1 as the previous key
        with patch.object(CapabilityManager, "_CURRENT_KEY_VERSION", 2):
            manager = CapabilityManager()

        # Sign a token with version 1 key (the "old" key)
        old_key = CapabilityManager._derive_signing_key(version=1)
        token = CapabilityToken(
            token_id="test-rotation-token",
            instance_id="inst-1",
            tenant_id="tenant-1",
            agent_id="agent-1",
            scope=CapabilityScope(),
            issued_at=time.time(),
            expires_at=time.time() + 3600,
        )
        # Manually sign with the old key
        token.signature = manager._sign(token, signing_key=old_key)

        # The manager (at version 2) should still verify via previous keys
        assert manager.verify_token(token) is True
