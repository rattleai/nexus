"""Agent capabilities — slug resolution and token-based privilege system.

Part 1: Capability Resolver
    Maps capability slugs (``myapp:items:write``) to tool name sets.
    Built from platform built-in + plugin-declared capabilities.
    Cached per-process, no database dependency.

Part 2: Capability Tokens
    Signed, scoped, time-limited tokens encoding agent permissions.
    Supports attenuation (sub-agents get monotonically reduced subsets),
    revocation via Redis, and key rotation.

Integrates with:
    - app/agents/tool_registry for platform capabilities
    - app/plugins.registry for plugin capabilities
    - app/agents/governance.py for approval workflow
    - app/agents/executor.py for token creation at instance startup
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings
from app.core.redis import redis_pool
from app.plugins.base import CapabilityDomain, ToolCapability  # noqa: F401

logger = structlog.stdlib.get_logger()


# ── Part 1: Capability Resolver (slug → tool names) ──────────────────


class CapabilityResolver:
    """Resolves capability slugs to flat tool name sets.

    Usage::

        from app.agents.capabilities import capability_resolver

        tools = capability_resolver.resolve(["myapp:items:read", "platform:ai"])
        # → {"config_list_products", "config_get_product", ..., "ai_complete", "ai_list_models"}
    """

    def __init__(self) -> None:
        self._slug_to_tools: dict[str, tuple[str, ...]] | None = None
        self._tool_to_slug: dict[str, str] | None = None
        self._domains: list[CapabilityDomain] | None = None

    def _build_index(self) -> None:
        """Build the capability → tools index from all sources."""
        from app.agents.tool_registry import PLATFORM_CAPABILITIES
        from app.plugins.registry import registry as plugin_registry

        slug_to_tools: dict[str, tuple[str, ...]] = {}
        tool_to_slug: dict[str, str] = {}
        domains: list[CapabilityDomain] = [PLATFORM_CAPABILITIES]

        # Platform capabilities
        for cap in PLATFORM_CAPABILITIES.capabilities:
            slug_to_tools[cap.slug] = cap.tools
            for tool_name in cap.tools:
                tool_to_slug[tool_name] = cap.slug

        # Plugin capabilities
        for plugin in plugin_registry:
            try:
                plugin_domains = plugin.get_capability_domains()
                for domain in plugin_domains:
                    domains.append(domain)
                    for cap in domain.capabilities:
                        slug_to_tools[cap.slug] = cap.tools
                        for tool_name in cap.tools:
                            tool_to_slug[tool_name] = cap.slug
            except Exception:
                logger.warning(
                    "capability_domain_load_failed",
                    plugin=plugin.name,
                    exc_info=True,
                )

        # Assign all three atomically (single-statement swap) so that a
        # concurrent resolve() never sees a partially-built index.
        self._slug_to_tools, self._tool_to_slug, self._domains = (
            slug_to_tools, tool_to_slug, domains,
        )

    def _ensure_index(self) -> None:
        if self._slug_to_tools is None:
            self._build_index()

    def resolve(self, capability_slugs: list[str]) -> set[str]:
        """Resolve a list of capability slugs to a set of tool names."""
        self._ensure_index()
        assert self._slug_to_tools is not None  # ensured above
        tools: set[str] = set()
        for slug in capability_slugs:
            if slug in self._slug_to_tools:
                tools.update(self._slug_to_tools[slug])
            else:
                logger.debug("capability_slug_unknown", slug=slug)
        return tools

    def resolve_agent_tools(self, definition: Any) -> list[str]:
        """Get the effective tool list for an agent definition.

        Resolution logic:
            - If ``definition.capabilities`` is non-empty, resolve those to
              tool names and union with ``definition.allowed_tools``.
            - If ``definition.capabilities`` is empty, fall back to
              ``definition.allowed_tools`` only (legacy behaviour).

        Returns a deduplicated, sorted list of tool names.
        """
        capabilities = getattr(definition, "capabilities", None) or []
        allowed_tools = getattr(definition, "allowed_tools", None) or []

        if capabilities:
            tools = self.resolve(capabilities)
            tools.update(allowed_tools)
            return sorted(tools)

        # Legacy: no capabilities configured, use raw allowed_tools
        return list(allowed_tools)

    def get_catalog(self) -> list[CapabilityDomain]:
        """Return the full capability catalog (platform + all plugins)."""
        self._ensure_index()
        assert self._domains is not None
        return list(self._domains)

    def get_capability_for_tool(self, tool_name: str) -> str | None:
        """Reverse lookup: which capability slug contains this tool?"""
        self._ensure_index()
        assert self._tool_to_slug is not None
        return self._tool_to_slug.get(tool_name)

    def invalidate(self) -> None:
        """Clear the cached index (e.g. after hot-reloading plugins in tests)."""
        self._slug_to_tools, self._tool_to_slug, self._domains = None, None, None


# Module-level singleton
capability_resolver = CapabilityResolver()


# ── Part 2: Capability Tokens (signed privilege tokens) ──────────────

# Default capability TTL (1 hour)
_DEFAULT_CAPABILITY_TTL_SECONDS = 3600

# Redis key for token revocation set (per-tenant)
_REVOKED_TOKEN_KEY = "agent:cap:revoked:{tenant_id}"


@dataclass
class CapabilityScope:
    """Defines what an agent instance is allowed to do."""

    # Allowed tool names (empty = all from definition)
    tools: list[str] = field(default_factory=list)
    # Allowed data access tables (empty = all from db_access_policy)
    data_tables: list[str] = field(default_factory=list)
    # Maximum spend for this capability (USD)
    max_spend_usd: float = 0.0
    # Data classification ceiling
    max_data_classification: str = "INTERNAL"  # PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED
    # Can this agent spawn sub-agents?
    can_delegate: bool = False
    # Can this agent access external tools?
    can_access_external_tools: bool = False
    # Additional custom permissions
    custom_permissions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "data_tables": self.data_tables,
            "max_spend_usd": self.max_spend_usd,
            "max_data_classification": self.max_data_classification,
            "can_delegate": self.can_delegate,
            "can_access_external_tools": self.can_access_external_tools,
            "custom_permissions": self.custom_permissions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityScope:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def attenuate(self, child_scope: CapabilityScope) -> CapabilityScope:
        """Create an attenuated scope for a sub-agent (monotonic reduction).

        The child's capabilities are the intersection of the parent's and
        the requested child scope. This ensures capability can only decrease
        when delegating.
        """
        # Tools: intersection
        if self.tools and child_scope.tools:
            child_tools = [t for t in child_scope.tools if t in self.tools]
        elif self.tools:
            child_tools = list(self.tools)
        else:
            child_tools = list(child_scope.tools)

        # Data tables: intersection
        if self.data_tables and child_scope.data_tables:
            child_tables = [t for t in child_scope.data_tables if t in self.data_tables]
        elif self.data_tables:
            child_tables = list(self.data_tables)
        else:
            child_tables = list(child_scope.data_tables)

        # Spend: minimum
        child_spend = min(
            self.max_spend_usd or float("inf"),
            child_scope.max_spend_usd or float("inf"),
        )
        if child_spend == float("inf"):
            child_spend = 0.0

        # Data classification: minimum (most restrictive)
        classification_order = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
        parent_level = classification_order.index(self.max_data_classification)
        child_level = classification_order.index(child_scope.max_data_classification)
        child_classification = classification_order[min(parent_level, child_level)]

        return CapabilityScope(
            tools=child_tools,
            data_tables=child_tables,
            max_spend_usd=child_spend,
            max_data_classification=child_classification,
            can_delegate=self.can_delegate and child_scope.can_delegate,
            can_access_external_tools=self.can_access_external_tools and child_scope.can_access_external_tools,
        )


@dataclass
class CapabilityToken:
    """A signed, scoped, time-limited capability token for an agent instance."""

    token_id: str = ""
    instance_id: str = ""
    tenant_id: str = ""
    agent_id: str = ""
    scope: CapabilityScope = field(default_factory=CapabilityScope)
    issued_at: float = 0.0
    expires_at: float = 0.0
    parent_token_id: str = ""  # Token ID of the parent (for attenuation chain)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "instance_id": self.instance_id,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "scope": self.scope.to_dict(),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "parent_token_id": self.parent_token_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityToken:
        scope = CapabilityScope.from_dict(data.get("scope", {}))
        return cls(
            token_id=data.get("token_id", ""),
            instance_id=data.get("instance_id", ""),
            tenant_id=data.get("tenant_id", ""),
            agent_id=data.get("agent_id", ""),
            scope=scope,
            issued_at=data.get("issued_at", 0.0),
            expires_at=data.get("expires_at", 0.0),
            parent_token_id=data.get("parent_token_id", ""),
            signature=data.get("signature", ""),
        )


class CapabilityManager:
    """Manages capability tokens for agent instances.

    Usage:
        manager = CapabilityManager()
        token = manager.create_token(
            instance_id=..., tenant_id=..., agent_id=...,
            scope=CapabilityScope(tools=["ai_complete"], max_spend_usd=1.0),
        )
        # Verify before tool call:
        if manager.verify_tool_access(token, "ai_complete"):
            ...
    """

    # Key version for rotation support. Bump this and set the corresponding
    # ENCRYPTION_KEY_V{N} env var to rotate signing keys. Tokens signed with
    # older versions can still be verified via _previous_keys.
    _CURRENT_KEY_VERSION = 1

    def __init__(self):
        self._signing_key = self._derive_signing_key(self._CURRENT_KEY_VERSION)
        # Cache previous key version for rotation grace period
        self._previous_keys: list[bytes] = []
        if self._CURRENT_KEY_VERSION > 1:
            self._previous_keys.append(
                self._derive_signing_key(self._CURRENT_KEY_VERSION - 1)
            )

    @staticmethod
    def _derive_signing_key(version: int = 1) -> bytes:
        """Derive a signing key for capability tokens using HKDF.

        Uses HKDF-SHA256 with a versioned info string for key rotation support.
        """
        # Try version-specific key first, fall back to primary
        source = (
            getattr(settings, f"ENCRYPTION_KEY_V{version}", "")
            or settings.ENCRYPTION_KEY
            or settings.SECRET_KEY
        )
        # Deterministic salt provides better key separation than salt=None
        # (RFC 5869 recommends a non-secret random value or application-specific constant).
        # The literal below is part of the KDF input — changing it invalidates
        # all previously signed capability tokens.
        salt = hashlib.sha256(b"nxs-capability-salt-v1").digest()
        hkdf = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=salt,
            info=f"capability-token-signing-v{version}".encode(),
        )
        return hkdf.derive(source.encode())

    def create_token(
        self,
        *,
        instance_id: str,
        tenant_id: str,
        agent_id: str,
        scope: CapabilityScope,
        ttl_seconds: int = _DEFAULT_CAPABILITY_TTL_SECONDS,
        parent_token_id: str = "",
    ) -> CapabilityToken:
        """Create a new signed capability token."""
        now = time.time()
        token = CapabilityToken(
            token_id=uuid.uuid4().hex,
            instance_id=instance_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            scope=scope,
            issued_at=now,
            expires_at=now + ttl_seconds,
            parent_token_id=parent_token_id,
        )
        token.signature = self._sign(token)
        return token

    def create_attenuated_token(
        self,
        parent_token: CapabilityToken,
        *,
        child_instance_id: str,
        child_agent_id: str,
        requested_scope: CapabilityScope,
        ttl_seconds: int | None = None,
    ) -> CapabilityToken:
        """Create an attenuated token for a sub-agent (monotonic capability reduction)."""
        if not self.verify_token(parent_token):
            raise CapabilityError("Cannot attenuate: parent token is invalid or expired")

        if not parent_token.scope.can_delegate:
            raise CapabilityError("Parent capability does not allow delegation")

        # Attenuate: child scope is the intersection of parent + requested
        attenuated_scope = parent_token.scope.attenuate(requested_scope)

        # TTL: child cannot exceed parent's remaining lifetime
        parent_remaining = parent_token.expires_at - time.time()
        child_ttl = int(parent_remaining) if ttl_seconds is None else min(ttl_seconds, int(parent_remaining))

        return self.create_token(
            instance_id=child_instance_id,
            tenant_id=parent_token.tenant_id,
            agent_id=child_agent_id,
            scope=attenuated_scope,
            ttl_seconds=max(1, child_ttl),
            parent_token_id=parent_token.token_id,
        )

    def verify_token(self, token: CapabilityToken) -> bool:
        """Verify a token's signature and expiry.

        Tries the current signing key first, then previous key versions
        for rotation grace period support.
        """
        if not token.signature:
            return False
        if time.time() > token.expires_at:
            logger.debug("capability_token_expired", token_id=token.token_id)
            return False
        # Try current key
        expected_sig = self._sign(token)
        if hmac.compare_digest(token.signature, expected_sig):
            return True
        # Try previous key versions for rotation grace period
        for prev_key in self._previous_keys:
            expected_sig = self._sign(token, signing_key=prev_key)
            if hmac.compare_digest(token.signature, expected_sig):
                logger.info("capability_token_verified_with_previous_key",
                            token_id=token.token_id)
                return True
        return False

    def verify_tool_access(self, token: CapabilityToken, tool_name: str) -> bool:
        """Check if a capability token allows access to a specific tool."""
        if not self.verify_token(token):
            return False
        # Empty tools list = all tools from definition are allowed
        if not token.scope.tools:
            return True
        return tool_name in token.scope.tools

    def verify_data_access(self, token: CapabilityToken, table_name: str) -> bool:
        """Check if a capability token allows access to a specific data table."""
        if not self.verify_token(token):
            return False
        if not token.scope.data_tables:
            return True
        return table_name in token.scope.data_tables

    def verify_data_classification(self, token: CapabilityToken, data_level: str) -> bool:
        """Check if a capability token allows access to data at the given classification level."""
        if not self.verify_token(token):
            return False
        classification_order = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
        try:
            token_level = classification_order.index(token.scope.max_data_classification)
            data_idx = classification_order.index(data_level)
        except ValueError:
            return False
        return data_idx <= token_level

    async def revoke_token(self, token: CapabilityToken) -> None:
        """Revoke a capability token by adding it to the Redis revocation set.

        The revocation entry auto-expires when the token would have expired,
        preventing unbounded growth of the revocation set.
        """
        key = _REVOKED_TOKEN_KEY.format(tenant_id=token.tenant_id)
        remaining_ttl = max(1, int(token.expires_at - time.time()))
        try:
            pipe = redis_pool.pipeline()
            pipe.sadd(key, token.token_id)
            pipe.expire(key, remaining_ttl + 60)  # Buffer for clock skew
            await pipe.execute()
            logger.info(
                "capability_token_revoked",
                token_id=token.token_id,
                tenant_id=token.tenant_id,
            )
        except Exception:
            logger.error("capability_token_revocation_failed", exc_info=True)
            raise CapabilityError("Failed to revoke token: Redis unavailable") from None

    async def is_revoked(self, token: CapabilityToken) -> bool:
        """Check if a token has been revoked.

        Fail-closed: returns True (revoked) if Redis is unavailable.
        """
        key = _REVOKED_TOKEN_KEY.format(tenant_id=token.tenant_id)
        try:
            return await redis_pool.sismember(key, token.token_id)
        except Exception:
            logger.error("capability_revocation_check_failed", exc_info=True)
            return True  # Fail-closed

    async def verify_token_full(self, token: CapabilityToken) -> bool:
        """Full verification including signature, expiry, and revocation check.

        Use this async method at critical enforcement points (tool execution,
        data access). The synchronous verify_token() is kept for hot paths
        where revocation checking is not needed.
        """
        if not self.verify_token(token):
            return False
        return not await self.is_revoked(token)

    def token_hash(self, token: CapabilityToken) -> str:
        """Get the hash of a token for storage in DB."""
        return hashlib.sha256(token.signature.encode()).hexdigest()

    def _sign(self, token: CapabilityToken, *, signing_key: bytes | None = None) -> str:
        """Create HMAC-SHA256 signature for a capability token."""
        key = signing_key or self._signing_key
        payload = json.dumps({
            "token_id": token.token_id,
            "instance_id": token.instance_id,
            "tenant_id": token.tenant_id,
            "agent_id": token.agent_id,
            "scope": token.scope.to_dict(),
            "issued_at": token.issued_at,
            "expires_at": token.expires_at,
            "parent_token_id": token.parent_token_id,
        }, sort_keys=True, separators=(",", ":"))
        return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


class CapabilityError(Exception):
    """Raised when a capability check fails."""


# Module-level singletons
capability_manager = CapabilityManager()
