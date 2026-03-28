"""Tests for the real-time threat detection engine."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.threat_detection import (
    AnomalyScore,
    BehavioralBaseline,
    RunMetrics,
    ThreatDetectionEngine,
    _ATLAS_MAPPING,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_engine(
    tenant_id: str = "tenant-1",
    agent_id: str = "agent-1",
    warn_sigma: float = 2.0,
    suspend_sigma: float = 3.0,
) -> ThreatDetectionEngine:
    return ThreatDetectionEngine(
        tenant_id=tenant_id,
        agent_id=agent_id,
        warn_sigma=warn_sigma,
        suspend_sigma=suspend_sigma,
    )


def _make_baseline(**overrides) -> BehavioralBaseline:
    """Create a realistic baseline with sensible defaults."""
    defaults = dict(
        total_runs=10,
        avg_steps=10,
        std_steps=2,
        avg_tokens=1000,
        std_tokens=200,
        avg_cost=0.5,
        std_cost=0.1,
        avg_tool_calls=5,
        std_tool_calls=1,
        avg_duration_ms=5000,
        std_duration_ms=1000,
        typical_tools=["ai_complete", "file_list"],
    )
    defaults.update(overrides)
    return BehavioralBaseline(**defaults)


def _make_redis_with_baseline(baseline: BehavioralBaseline | None = None) -> AsyncMock:
    """Create a Redis mock that returns the given baseline on get()."""
    mock_redis = AsyncMock()
    if baseline is not None:
        mock_redis.get = AsyncMock(return_value=json.dumps(baseline.to_dict()))
    else:
        mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()
    return mock_redis


# ── TestBehavioralBaseline ───────────────────────────────────────────


class TestBehavioralBaseline:
    """BehavioralBaseline serialization and defaults."""

    def test_baseline_round_trip(self):
        baseline = _make_baseline()
        data = baseline.to_dict()
        restored = BehavioralBaseline.from_dict(data)

        assert restored.total_runs == baseline.total_runs
        assert restored.avg_steps == baseline.avg_steps
        assert restored.std_steps == baseline.std_steps
        assert restored.avg_tokens == baseline.avg_tokens
        assert restored.std_tokens == baseline.std_tokens
        assert restored.avg_cost == baseline.avg_cost
        assert restored.std_cost == baseline.std_cost
        assert restored.avg_tool_calls == baseline.avg_tool_calls
        assert restored.std_tool_calls == baseline.std_tool_calls
        assert restored.typical_tools == baseline.typical_tools
        assert restored.avg_duration_ms == baseline.avg_duration_ms
        assert restored.std_duration_ms == baseline.std_duration_ms

    def test_empty_baseline(self):
        baseline = BehavioralBaseline()
        assert baseline.total_runs == 0
        assert baseline.avg_steps == 0.0
        assert baseline.std_steps == 0.0
        assert baseline.avg_tokens == 0.0
        assert baseline.avg_cost == 0.0
        assert baseline.avg_tool_calls == 0.0
        assert baseline.avg_duration_ms == 0.0


# ── TestBaselineUpdates ──────────────────────────────────────────────


class TestBaselineUpdates:
    """update_baseline applies Welford's online algorithm correctly."""

    @pytest.mark.asyncio
    async def test_first_run_sets_mean(self):
        mock_redis = _make_redis_with_baseline(None)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(steps=10, tokens=500, cost_usd=0.1, tool_calls=3, duration_ms=2000)
            await engine.update_baseline(metrics)

        # Capture what was stored
        stored_call = mock_redis.setex.call_args
        stored_data = json.loads(stored_call[0][2])
        assert stored_data["avg_steps"] == 10.0
        assert stored_data["std_steps"] == 0.0

    @pytest.mark.asyncio
    async def test_second_run_updates_mean(self):
        # First run baseline: avg_steps=10, total_runs=1
        first_baseline = BehavioralBaseline(
            total_runs=1,
            avg_steps=10.0,
            std_steps=0.0,
            avg_tokens=0,
            avg_cost=0,
            avg_tool_calls=0,
            avg_duration_ms=0,
        )
        mock_redis = _make_redis_with_baseline(first_baseline)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(steps=20, tokens=0, cost_usd=0, tool_calls=0, duration_ms=0)
            await engine.update_baseline(metrics)

        stored_call = mock_redis.setex.call_args
        stored_data = json.loads(stored_call[0][2])
        assert stored_data["avg_steps"] == 15.0

    @pytest.mark.asyncio
    async def test_typical_tools_tracked(self):
        mock_redis = _make_redis_with_baseline(None)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(
                steps=5, tokens=100, cost_usd=0.01,
                tool_calls=2, tools_used=["a", "b"], duration_ms=1000,
            )
            await engine.update_baseline(metrics)

        stored_call = mock_redis.setex.call_args
        stored_data = json.loads(stored_call[0][2])
        assert "a" in stored_data["typical_tools"]
        assert "b" in stored_data["typical_tools"]


# ── TestAnomalyScoring ───────────────────────────────────────────────


class TestAnomalyScoring:
    """score_run produces correct anomaly scores against baselines."""

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        baseline = _make_baseline(total_runs=3)
        mock_redis = _make_redis_with_baseline(baseline)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(steps=100)
            score = await engine.score_run("inst-1", metrics)

        assert score.total_score == 0.0

    @pytest.mark.asyncio
    async def test_normal_run(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            # Metrics close to baseline averages
            metrics = RunMetrics(
                steps=11, tokens=1050, cost_usd=0.52,
                tool_calls=5, tools_used=["ai_complete"],
                duration_ms=5200,
            )
            score = await engine.score_run("inst-1", metrics)

        # Normal run should have low total score (below warn threshold of 2.0)
        assert score.total_score < 2.0

    @pytest.mark.asyncio
    async def test_high_steps_flagged(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine()
            # steps=500, baseline avg=10, std=2 → z-score = (500-10)/2 = 245
            metrics = RunMetrics(steps=500, tokens=1000, cost_usd=0.5, tool_calls=5, duration_ms=5000)
            score = await engine.score_run("inst-1", metrics)

        assert "steps" in score.factors
        assert score.factors["steps"] > 2.0

    @pytest.mark.asyncio
    async def test_high_cost_flagged(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine()
            # cost=100, baseline avg=0.5, std=0.1 → z-score = (100-0.5)/0.1 = 995
            metrics = RunMetrics(steps=10, tokens=1000, cost_usd=100, tool_calls=5, duration_ms=5000)
            score = await engine.score_run("inst-1", metrics)

        assert "cost" in score.factors

    @pytest.mark.asyncio
    async def test_unusual_tools_flagged(self):
        baseline = _make_baseline(typical_tools=["a", "b"])
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine()
            metrics = RunMetrics(
                steps=10, tokens=1000, cost_usd=0.5,
                tool_calls=5, tools_used=["never_seen"],
                duration_ms=5000,
            )
            score = await engine.score_run("inst-1", metrics)

        assert "unusual_tools" in score.factors

    @pytest.mark.asyncio
    async def test_warn_action(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine(warn_sigma=2.0, suspend_sigma=3.0)
            # Steps z-score = (20-10)/2 = 5.0 but let's target warn range [2,3)
            # z = (14-10)/2 = 2.0 exactly at warn threshold
            metrics = RunMetrics(steps=14, tokens=1000, cost_usd=0.5, tool_calls=5, duration_ms=5000)
            score = await engine.score_run("inst-1", metrics)

        assert score.total_score >= 2.0
        assert score.action == "warn" or score.action == "suspend"

    @pytest.mark.asyncio
    async def test_suspend_action(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine(warn_sigma=2.0, suspend_sigma=3.0)
            # Steps z-score = (500-10)/2 = 245 → well above 3.0
            metrics = RunMetrics(steps=500, tokens=1000, cost_usd=0.5, tool_calls=5, duration_ms=5000)
            score = await engine.score_run("inst-1", metrics)

        assert score.total_score >= 3.0
        assert score.action == "suspend"

    def test_tool_calls_atlas_key(self):
        """The 'tool_calls' factor maps to 'excessive_tool_calls' in ATLAS, not 'excessive_steps'."""
        assert "excessive_tool_calls" in _ATLAS_MAPPING
        assert _ATLAS_MAPPING["excessive_tool_calls"] == "AML.T0044"

    def test_duration_atlas_key(self):
        """The 'duration' factor maps to 'excessive_duration' in ATLAS."""
        assert "excessive_duration" in _ATLAS_MAPPING
        assert _ATLAS_MAPPING["excessive_duration"] == "AML.T0040"

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.settings") as mock_settings,
        ):
            mock_settings.AGENT_THREAT_DETECTION_ENABLED = False
            mock_settings.AGENT_THREAT_ANOMALY_WARN_SIGMA = 2.0
            mock_settings.AGENT_THREAT_ANOMALY_SUSPEND_SIGMA = 3.0

            engine = _make_engine()
            metrics = RunMetrics(steps=500)
            score = await engine.score_run("inst-1", metrics)

        assert score.total_score == 0.0
        assert score.factors == {}
        assert score.action == "none"


# ── TestThreatAttacks ────────────────────────────────────────────────


class TestThreatAttacks:
    """Attack simulations: resource exhaustion and cost spikes."""

    @pytest.mark.asyncio
    async def test_resource_exhaustion(self):
        """Anomalous steps count (200 vs avg 10) triggers suspend."""
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine(warn_sigma=2.0, suspend_sigma=3.0)
            metrics = RunMetrics(
                steps=200, tokens=1000, cost_usd=0.5,
                tool_calls=5, duration_ms=5000,
            )
            score = await engine.score_run("inst-1", metrics)

        # z-score for steps = (200-10)/2 = 95 → suspend
        assert score.action == "suspend"

    @pytest.mark.asyncio
    async def test_cost_spike(self):
        """Anomalous cost ($50 vs avg $0.50) triggers suspend."""
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.agents.threat_detection.ThreatDetectionEngine._emit_threat_event", new_callable=AsyncMock),
        ):
            engine = _make_engine(warn_sigma=2.0, suspend_sigma=3.0)
            metrics = RunMetrics(
                steps=10, tokens=1000, cost_usd=50.0,
                tool_calls=5, duration_ms=5000,
            )
            score = await engine.score_run("inst-1", metrics)

        # z-score for cost = (50-0.5)/0.1 = 495 → suspend
        assert score.action == "suspend"


# ── TestNonFiniteMetrics ────────────────────────────────────────────


class TestNonFiniteMetrics:
    """Validate that NaN and Infinity metric values are safely skipped."""

    @pytest.mark.asyncio
    async def test_nan_metric_skipped(self):
        """NaN metric value is skipped without crashing."""
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(
                steps=10, tokens=1000, cost_usd=float("nan"),
                tool_calls=5, duration_ms=5000,
            )
            # Should not raise — NaN is safely skipped
            score = await engine.score_run("inst-1", metrics)

        # "cost" should NOT appear in factors since NaN was skipped
        assert "cost" not in score.factors

    @pytest.mark.asyncio
    async def test_infinity_metric_skipped(self):
        """Infinity metric value is skipped without crashing."""
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with patch("app.agents.threat_detection.redis_pool", mock_redis):
            engine = _make_engine()
            metrics = RunMetrics(
                steps=10, tokens=1000, cost_usd=float("inf"),
                tool_calls=5, duration_ms=5000,
            )
            # Should not raise — Infinity is safely skipped
            score = await engine.score_run("inst-1", metrics)

        assert "cost" not in score.factors


# ── TestDLQFallback ─────────────────────────────────────────────────


class TestDLQFallback:
    """Validate DLQ fallback when threat event emission fails."""

    @pytest.mark.asyncio
    async def test_dlq_used_when_emit_fails(self):
        """When event emission fails, the event is enqueued to the DLQ."""
        baseline = _make_baseline()
        mock_redis = _make_redis_with_baseline(baseline)

        with (
            patch("app.agents.threat_detection.redis_pool", mock_redis),
            patch("app.core.events.emit", new_callable=AsyncMock, side_effect=Exception("event bus down")),
            patch("app.agents.security_dlq.enqueue_dead_letter", new_callable=AsyncMock) as mock_dlq,
        ):
            engine = _make_engine(warn_sigma=2.0, suspend_sigma=3.0)
            # Steps z-score = (500-10)/2 = 245 → triggers suspend → emits event
            metrics = RunMetrics(steps=500, tokens=1000, cost_usd=0.5, tool_calls=5, duration_ms=5000)
            score = await engine.score_run("inst-1", metrics)

        assert score.action == "suspend"
        mock_dlq.assert_called_once()
        call_args = mock_dlq.call_args
        assert call_args[0][0] == "threat_detected"
