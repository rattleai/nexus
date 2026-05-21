"""Policy gate (P3.1) — Cedar-based authorization for connector tool calls.

When ``CONNECTOR_CEDAR_ENABLED`` is True, every tool invocation passes
through the Cedar policy engine with:

    principal = User | Agent
    action    = "invoke"
    resource  = ConnectorTool { slug, connector, risk }
    context   = { time, arguments, hitl_approved }

Policies live in ``CONNECTOR_CEDAR_POLICY_DIR`` and are loaded at startup.
A default policy permits low/medium-risk tools without approval and
forbids high-risk tools until a HITL approval event is recorded.

When Cedar is disabled (default in dev, recommended until you've authored
policies), the gate is a no-op — downstream governance still runs via the
existing ``CapabilityResolver`` + ``GovernanceEngine`` path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.connectors.models import ConnectorDefinition

logger = structlog.stdlib.get_logger()


class PolicyDenied(Exception):
    """Raised when the policy engine rejects a tool call."""


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class PolicyGate:
    """Cedar-based connector tool authorization gate."""

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._policies_loaded = False

    def _lazy_load(self) -> Any | None:
        if self._policies_loaded:
            return self._engine
        self._policies_loaded = True

        if not settings.CONNECTOR_CEDAR_ENABLED:
            return None

        try:
            import cedarpy  # type: ignore
        except Exception:
            logger.info("cedar_sdk_not_installed_policy_gate_disabled")
            return None

        policy_dir = Path(settings.CONNECTOR_CEDAR_POLICY_DIR)
        if not policy_dir.exists():
            logger.info("cedar_policy_dir_missing", path=str(policy_dir))
            return None

        policy_texts: list[str] = []
        for p in sorted(policy_dir.glob("*.cedar")):
            try:
                policy_texts.append(p.read_text())
            except Exception:
                logger.warning(
                    "cedar_policy_load_failed",
                    path=str(p),
                    exc_info=True,
                )

        if not policy_texts:
            return None

        try:
            self._engine = cedarpy.Engine(policies="\n".join(policy_texts))
            logger.info(
                "cedar_policy_gate_ready",
                policy_count=len(policy_texts),
            )
        except Exception:
            logger.warning("cedar_engine_init_failed", exc_info=True)
            self._engine = None

        return self._engine

    async def authorize(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        agent_id: uuid.UUID | None,
        connector_def: ConnectorDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PolicyDecision:
        """Evaluate the Cedar policy and raise PolicyDenied on deny."""
        engine = self._lazy_load()
        if engine is None:
            return PolicyDecision(allowed=True, reason="cedar_disabled")

        principal = (
            f'Agent::"{agent_id}"'
            if agent_id
            else f'User::"{actor_user_id}"'
            if actor_user_id
            else 'System::"anonymous"'
        )
        resource = f'ConnectorTool::"{connector_def.slug}:{tool_name}"'

        request = {
            "principal": principal,
            "action": 'Action::"invoke"',
            "resource": resource,
            "context": {
                "tenant_id": str(tenant_id),
                "connector": connector_def.slug,
                "trust_level": connector_def.trust_level.value,
                "arguments": arguments,
            },
        }

        try:
            result = engine.is_authorized(request)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("cedar_evaluation_failed", exc_info=True)
            # Fail-closed when Cedar can't evaluate
            raise PolicyDenied("Policy evaluation error") from None

        allowed = bool(getattr(result, "allowed", False) or result.get("allowed"))
        reason = getattr(result, "reason", "") or result.get("reason", "")

        if not allowed:
            raise PolicyDenied(reason or "forbidden by Cedar policy")

        return PolicyDecision(allowed=True, reason=reason)


policy_gate = PolicyGate()
