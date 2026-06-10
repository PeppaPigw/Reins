"""Tests for trust & reputation engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.trust import (
    AutonomyLevel,
    ReputationEvent,
    ReputationEventKind,
    TrustDecay,
    TrustDecision,
    TrustDimension,
    TrustEngine,
    TrustProfile,
    TrustScore,
    TrustThresholds,
)


@pytest.fixture
def engine() -> TrustEngine:
    return TrustEngine()


def _event(agent_id="agent-1", kind=ReputationEventKind.SUCCESS,
           dimension=TrustDimension.CORRECTNESS, magnitude=1.0):
    return ReputationEvent(
        agent_id=agent_id,
        kind=kind,
        dimension=dimension,
        magnitude=magnitude,
    )


def test_new_agent_starts_supervised(engine):
    profile = engine.get_profile("agent-1")
    assert profile.autonomy_level == AutonomyLevel.SUPERVISED
    assert profile.total_events == 0


def test_success_increases_score(engine):
    engine.record_event(_event(kind=ReputationEventKind.SUCCESS))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score > 0.5


def test_failure_decreases_score(engine):
    engine.record_event(_event(kind=ReputationEventKind.FAILURE))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score < 0.5


def test_violation_large_penalty(engine):
    engine.record_event(_event(kind=ReputationEventKind.VIOLATION))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score == pytest.approx(0.2)


def test_recovery_bonus(engine):
    engine.record_event(_event(kind=ReputationEventKind.FAILURE))
    engine.record_event(_event(kind=ReputationEventKind.RECOVERY))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score > 0.4


def test_score_clamped_at_zero(engine):
    for _ in range(50):
        engine.record_event(_event(kind=ReputationEventKind.VIOLATION))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score == 0.0


def test_score_clamped_at_one(engine):
    for _ in range(200):
        engine.record_event(_event(kind=ReputationEventKind.SUCCESS))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score == 1.0


def test_autonomy_progression(engine):
    thresholds = TrustThresholds(
        guided_threshold=0.4,
        autonomous_threshold=0.7,
        fully_trusted_threshold=0.9,
    )
    eng = TrustEngine(thresholds=thresholds)

    for dim in TrustDimension:
        for _ in range(50):
            eng.record_event(_event(dimension=dim, kind=ReputationEventKind.SUCCESS))

    profile = eng.get_profile("agent-1")
    assert profile.autonomy_level in (AutonomyLevel.AUTONOMOUS, AutonomyLevel.FULLY_TRUSTED)


def test_evaluate_allows_when_sufficient(engine):
    for dim in TrustDimension:
        for _ in range(20):
            engine.record_event(_event(dimension=dim, kind=ReputationEventKind.SUCCESS))

    decision = engine.evaluate("agent-1", min_autonomy=AutonomyLevel.GUIDED)
    assert decision.allowed


def test_evaluate_blocks_when_insufficient(engine):
    decision = engine.evaluate("agent-1", min_autonomy=AutonomyLevel.AUTONOMOUS)
    assert not decision.allowed
    assert "Insufficient" in decision.reason


def test_evaluate_blocks_on_dimension(engine):
    for dim in TrustDimension:
        for _ in range(20):
            engine.record_event(_event(dimension=dim, kind=ReputationEventKind.SUCCESS))

    for _ in range(30):
        engine.record_event(_event(
            dimension=TrustDimension.SAFETY,
            kind=ReputationEventKind.VIOLATION,
        ))

    decision = engine.evaluate(
        "agent-1",
        required_dimension=TrustDimension.SAFETY,
        min_autonomy=AutonomyLevel.GUIDED,
    )
    assert not decision.allowed
    assert decision.limiting_dimension == TrustDimension.SAFETY


def test_multiple_agents_independent(engine):
    engine.record_event(_event(agent_id="a", kind=ReputationEventKind.SUCCESS))
    engine.record_event(_event(agent_id="b", kind=ReputationEventKind.VIOLATION))

    profile_a = engine.get_profile("a")
    profile_b = engine.get_profile("b")
    score_a = next(s for s in profile_a.scores if s.dimension == TrustDimension.CORRECTNESS)
    score_b = next(s for s in profile_b.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score_a.score > score_b.score


def test_confidence_increases_with_samples(engine):
    for _ in range(5):
        engine.record_event(_event())
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.confidence == 0.5

    for _ in range(5):
        engine.record_event(_event())
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.confidence == 1.0


def test_decay_exponential(engine):
    engine.record_event(_event(kind=ReputationEventKind.SUCCESS))
    future = datetime.now(UTC) + timedelta(hours=336)
    deltas = engine.decay_scores(reference_time=future)
    assert "agent-1" in deltas
    assert deltas["agent-1"] > 0

    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score < 0.55


def test_decay_none_preserves():
    eng = TrustEngine(thresholds=TrustThresholds(decay=TrustDecay.NONE))
    eng.record_event(_event(kind=ReputationEventKind.SUCCESS))
    future = datetime.now(UTC) + timedelta(hours=1000)
    deltas = eng.decay_scores(reference_time=future)
    assert len(deltas) == 0


def test_decay_linear():
    eng = TrustEngine(thresholds=TrustThresholds(decay=TrustDecay.LINEAR))
    eng.record_event(_event(kind=ReputationEventKind.SUCCESS))
    future = datetime.now(UTC) + timedelta(hours=100)
    deltas = eng.decay_scores(reference_time=future)
    assert "agent-1" in deltas


def test_timeout_event(engine):
    engine.record_event(_event(kind=ReputationEventKind.TIMEOUT))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score < 0.5


def test_escalation_event(engine):
    engine.record_event(_event(kind=ReputationEventKind.ESCALATION))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score < 0.5


def test_magnitude_scales_effect(engine):
    engine.record_event(_event(kind=ReputationEventKind.SUCCESS, magnitude=2.0))
    profile = engine.get_profile("agent-1")
    score = next(s for s in profile.scores if s.dimension == TrustDimension.CORRECTNESS)
    assert score.score == pytest.approx(0.6)


def test_stats_empty():
    eng = TrustEngine()
    stats = eng.get_stats()
    assert stats["total_agents"] == 0
    assert stats["total_events"] == 0


def test_stats_with_data(engine):
    for _ in range(5):
        engine.record_event(_event(agent_id="a"))
    for _ in range(3):
        engine.record_event(_event(agent_id="b"))
    stats = engine.get_stats()
    assert stats["total_agents"] == 2
    assert stats["total_events"] == 8
    assert "autonomy_distribution" in stats
    assert stats["avg_composite"] > 0


def test_composite_weights_safety_higher(engine):
    engine.record_event(_event(
        dimension=TrustDimension.SAFETY,
        kind=ReputationEventKind.VIOLATION,
    ))
    engine.record_event(_event(
        dimension=TrustDimension.EFFICIENCY,
        kind=ReputationEventKind.VIOLATION,
    ))
    profile = engine.get_profile("agent-1")
    safety_score = next(s for s in profile.scores if s.dimension == TrustDimension.SAFETY)
    efficiency_score = next(s for s in profile.scores if s.dimension == TrustDimension.EFFICIENCY)
    assert safety_score.score == efficiency_score.score

    decision = engine.evaluate("agent-1")
    assert decision.composite_score < 0.5


def test_profile_tracks_event_count(engine):
    for _ in range(7):
        engine.record_event(_event())
    profile = engine.get_profile("agent-1")
    assert profile.total_events == 7


def test_profile_tracks_last_event(engine):
    engine.record_event(_event())
    profile = engine.get_profile("agent-1")
    assert profile.last_event_at is not None
