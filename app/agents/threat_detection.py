"""Real-time threat detection engine for agent behavioral analysis.

Provides:
    - Behavioral baselines: Per-agent statistical profiles (avg steps, tokens, tools, cost)
    - Anomaly scoring: Real-time comparison of current run against baseline
    - Alert thresholds: Configurable per-agent (warn at 2-sigma, suspend at 3-sigma)
    - Automated response: Pause/suspend on high anomaly scores
    - MITRE ATLAS mapping: Map anomalies to ATLAS technique IDs

Integrates with:
    - app/agents/runtime.py via AgentStepCompleted event hooks
    - app/agents/events.py for AgentThreatDetected events
    - app/core/redis for baseline storage and real-time counters
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis keys
_BASELINE_KEY = "agent:threat:baseline:{tenant_id}:{agent_id}"
_RUN_METRICS_KEY = "agent:threat:run:{tenant_id}:{instance_id}"

# MITRE ATLAS technique mapping for detected anomalies
_ATLAS_MAPPING = {
    "excessive_steps": "AML.T0040",  # Search for Victim's Publicly Available Research Materials
    "excessive_tokens": "AML.T0043",  # Craft Adversarial Data
    "excessive_cost": "AML.T0024",  # Exfiltration via ML API
    "excessive_tool_calls": "AML.T0044",  # Full ML Model Access
    "excessive_duration": "AML.T0040",  # Resource exhaustion
    "unusual_tools": "AML.T0044",  # Full ML Model Access
    "rapid_a2a_messages": "AML.T0048",  # Command and Control via ML Service
    "cost_outlier": "AML.T0024",  # Exfiltration via ML API
}


@dataclass
class BehavioralBaseline:
    """Statistical profile for an agent definition (updated after each run)."""

    total_runs: int = 0
    avg_steps: float = 0.0
    std_steps: float = 0.0
    avg_tokens: float = 0.0
    std_tokens: float = 0.0
    avg_cost: float = 0.0
    std_cost: float = 0.0
    avg_tool_calls: float = 0.0
    std_tool_calls: float = 0.0
    typical_tools: list[str] = field(default_factory=list)
    avg_duration_ms: float = 0.0
    std_duration_ms: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "avg_steps": self.avg_steps,
            "std_steps": self.std_steps,
            "avg_tokens": self.avg_tokens,
            "std_tokens": self.std_tokens,
            "avg_cost": self.avg_cost,
            "std_cost": self.std_cost,
            "avg_tool_calls": self.avg_tool_calls,
            "std_tool_calls": self.std_tool_calls,
            "typical_tools": self.typical_tools,
            "avg_duration_ms": self.avg_duration_ms,
            "std_duration_ms": self.std_duration_ms,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BehavioralBaseline:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AnomalyScore:
    """Anomaly scoring result for a current run."""

    total_score: float = 0.0
    factors: dict[str, float] = field(default_factory=dict)
    action: str = "none"  # "none", "warn", "pause", "suspend"
    atlas_techniques: list[str] = field(default_factory=list)


@dataclass
class RunMetrics:
    """Metrics collected during an agent run for threat analysis."""

    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)
    duration_ms: int = 0
    a2a_messages_sent: int = 0


class ThreatDetectionEngine:
    """Real-time behavioral anomaly detection for agent runs.

    Usage:
        engine = ThreatDetectionEngine(tenant_id=..., agent_id=...)

        # During agent run: track metrics
        await engine.record_step(instance_id, step_metrics)

        # After run: score anomalies and update baseline
        score = await engine.score_run(instance_id, run_metrics)
        await engine.update_baseline(run_metrics)
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        warn_sigma: float = 0.0,
        suspend_sigma: float = 0.0,
    ):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.warn_sigma = warn_sigma or settings.AGENT_THREAT_ANOMALY_WARN_SIGMA
        self.suspend_sigma = suspend_sigma or settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA

    async def get_baseline(self) -> BehavioralBaseline:
        """Load the behavioral baseline from Redis."""
        key = _BASELINE_KEY.format(tenant_id=self.tenant_id, agent_id=self.agent_id)
        try:
            raw = await redis_pool.get(key)
            if raw:
                return BehavioralBaseline.from_dict(json.loads(raw))
        except Exception:
            logger.debug("threat_baseline_load_failed", exc_info=True)
        return BehavioralBaseline()

    async def update_baseline(self, metrics: RunMetrics) -> None:
        """Update the behavioral baseline with metrics from a completed run.

        Uses Welford's online algorithm for running mean and standard deviation.
        """
        baseline = await self.get_baseline()
        n = baseline.total_runs + 1

        def update_stat(old_mean: float, old_std: float, new_value: float) -> tuple[float, float]:
            """Welford's online algorithm for mean and std dev."""
            if not math.isfinite(new_value):
                return old_mean, old_std  # Skip NaN/Inf values
            if n == 1:
                return float(new_value), 0.0
            delta = new_value - old_mean
            new_mean = old_mean + delta / n
            delta2 = new_value - new_mean
            # Running M2 (sum of squared differences)
            old_m2 = old_std**2 * (n - 1) if n > 1 else 0
            new_m2 = old_m2 + delta * delta2
            new_std = math.sqrt(new_m2 / n) if n > 0 else 0.0
            return new_mean, new_std

        baseline.avg_steps, baseline.std_steps = update_stat(
            baseline.avg_steps,
            baseline.std_steps,
            metrics.steps,
        )
        baseline.avg_tokens, baseline.std_tokens = update_stat(
            baseline.avg_tokens,
            baseline.std_tokens,
            metrics.tokens,
        )
        baseline.avg_cost, baseline.std_cost = update_stat(
            baseline.avg_cost,
            baseline.std_cost,
            metrics.cost_usd,
        )
        baseline.avg_tool_calls, baseline.std_tool_calls = update_stat(
            baseline.avg_tool_calls,
            baseline.std_tool_calls,
            metrics.tool_calls,
        )
        baseline.avg_duration_ms, baseline.std_duration_ms = update_stat(
            baseline.avg_duration_ms,
            baseline.std_duration_ms,
            metrics.duration_ms,
        )

        # Update typical tools (most frequently used)
        tool_counts: dict[str, int] = {}
        for tool in baseline.typical_tools + metrics.tools_used:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        baseline.typical_tools = sorted(tool_counts, key=tool_counts.get, reverse=True)[:20]

        baseline.total_runs = n
        baseline.last_updated = time.time()

        # Persist to Redis
        key = _BASELINE_KEY.format(tenant_id=self.tenant_id, agent_id=self.agent_id)
        try:
            await redis_pool.setex(key, 86400 * 30, json.dumps(baseline.to_dict()))
        except Exception:
            logger.debug("threat_baseline_save_failed", exc_info=True)

    async def score_run(self, instance_id: str, metrics: RunMetrics) -> AnomalyScore:
        """Score a run for anomalous behavior against the baseline.

        Returns an AnomalyScore with per-factor breakdown.
        """
        if not settings.AGENT_THREAT_DETECTION_ENABLED:
            return AnomalyScore()

        baseline = await self.get_baseline()

        # Need at least 5 runs for meaningful baselines
        if baseline.total_runs < 5:
            return AnomalyScore()

        score = AnomalyScore()

        # Score each factor (z-score: how many standard deviations from mean)
        factors = {
            "steps": (metrics.steps, baseline.avg_steps, baseline.std_steps, "excessive_steps"),
            "tokens": (metrics.tokens, baseline.avg_tokens, baseline.std_tokens, "excessive_tokens"),
            "cost": (metrics.cost_usd, baseline.avg_cost, baseline.std_cost, "cost_outlier"),
            "tool_calls": (
                metrics.tool_calls,
                baseline.avg_tool_calls,
                baseline.std_tool_calls,
                "excessive_tool_calls",
            ),
            "duration": (metrics.duration_ms, baseline.avg_duration_ms, baseline.std_duration_ms, "excessive_duration"),
        }

        z_scores: list[float] = []
        for name, (value, mean, std, atlas_key) in factors.items():
            # Guard against NaN/Infinity from corrupted metrics
            if not math.isfinite(value) or not math.isfinite(mean) or not math.isfinite(std):
                logger.warning(
                    "threat_detection_non_finite_metric",
                    name=name,
                    value=value,
                    mean=mean,
                    std=std,
                )
                continue

            if std > 0:
                z = abs(value - mean) / std
            elif value > mean * 2:
                z = 3.0  # No variance data but value is >2x mean
            else:
                z = 0.0

            if z > 1.0:
                score.factors[name] = round(z, 2)
                if atlas_key in _ATLAS_MAPPING:
                    score.atlas_techniques.append(_ATLAS_MAPPING[atlas_key])
            z_scores.append(z)

        # Check for unusual tools
        if baseline.typical_tools and metrics.tools_used:
            unusual = set(metrics.tools_used) - set(baseline.typical_tools)
            if unusual:
                score.factors["unusual_tools"] = len(unusual)
                score.atlas_techniques.append(_ATLAS_MAPPING.get("unusual_tools", ""))

        # Aggregate score: max of individual z-scores
        score.total_score = max(z_scores) if z_scores else 0.0

        # Determine action based on thresholds
        if score.total_score >= self.suspend_sigma:
            score.action = "suspend"
        elif score.total_score >= self.warn_sigma:
            score.action = "warn"

        # Emit event if action required
        if score.action != "none":
            await self._emit_threat_event(instance_id, score)

        return score

    async def record_step_metrics(
        self,
        instance_id: str,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        tool_name: str = "",
    ) -> None:
        """Record per-step metrics for real-time anomaly detection."""
        key = _RUN_METRICS_KEY.format(tenant_id=self.tenant_id, instance_id=instance_id)
        try:
            entry = json.dumps(
                {
                    "ts": time.time(),
                    "tokens": tokens,
                    "cost": cost_usd,
                    "tool": tool_name,
                }
            )
            pipe = redis_pool.pipeline()
            pipe.lpush(key, entry)
            pipe.expire(key, 3600)
            await pipe.execute()
        except Exception:
            logger.debug("threat_step_metrics_failed", exc_info=True)

    async def _emit_threat_event(self, instance_id: str, score: AnomalyScore) -> None:
        """Emit AgentThreatDetected event with DLQ fallback."""
        from app.agents.events import AgentThreatDetected
        from app.core.events import emit

        try:
            await emit(
                AgentThreatDetected(
                    tenant_id=self.tenant_id,
                    instance_id=instance_id,
                    agent_id=self.agent_id,
                    anomaly_score=score.total_score,
                    factors=score.factors,
                    action_taken=score.action,
                    atlas_technique=score.atlas_techniques[0] if score.atlas_techniques else "",
                ),
                durable=True,
            )
        except Exception:
            logger.error("threat_event_emission_failed", exc_info=True)
            from app.agents.security_dlq import enqueue_dead_letter

            await enqueue_dead_letter(
                "threat_detected",
                {
                    "tenant_id": self.tenant_id,
                    "instance_id": instance_id,
                    "agent_id": self.agent_id,
                    "anomaly_score": score.total_score,
                    "action": score.action,
                },
            )

        logger.warning(
            "agent_threat_detected",
            tenant_id=self.tenant_id,
            instance_id=instance_id,
            agent_id=self.agent_id,
            anomaly_score=score.total_score,
            action=score.action,
            factors=score.factors,
        )
