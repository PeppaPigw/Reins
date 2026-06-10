"""Tests for reputation engine with trust scoring and endorsements."""

from __future__ import annotations

import pytest

from reins.reputation import (
    AgentReputation,
    Endorsement,
    FeedbackKind,
    ReputationEngine,
    ReputationEvent,
    ReputationPolicy,
    ReputationStats,
    ReputationTier,
)


@pytest.fixture
def engine() -> ReputationEngine:
    return ReputationEngine()


def test_get_reputation_default(engine):
    rep = engine.get_reputation("agent-1")
    assert rep.score == 50.0
    assert rep.tier == ReputationTier.ESTABLISHED


def test_record_success(engine):
    engine.record_success("agent-1", points=10.0)
    rep = engine.get_reputation("agent-1")
    assert rep.score == 60.0
    assert rep.streak == 1


def test_record_multiple_successes(engine):
    engine.record_success("agent-1")
    engine.record_success("agent-1")
    rep = engine.get_reputation("agent-1")
    assert rep.streak == 2


def test_record_failure(engine):
    engine.record_failure("agent-1", points=5.0)
    rep = engine.get_reputation("agent-1")
    assert rep.score == 45.0
    assert rep.streak == 0


def test_score_capped_at_100(engine):
    for _ in range(20):
        engine.record_success("agent-1", points=10.0)
    rep = engine.get_reputation("agent-1")
    assert rep.score == 100.0


def test_score_floored_at_0(engine):
    for _ in range(20):
        engine.record_failure("agent-1", points=10.0)
    rep = engine.get_reputation("agent-1")
    assert rep.score == 0.0


def test_tier_progression(engine):
    for _ in range(10):
        engine.record_success("agent-1", points=5.0)
    rep = engine.get_reputation("agent-1")
    assert rep.tier == ReputationTier.ELITE


def test_tier_demotion(engine):
    for _ in range(10):
        engine.record_failure("agent-1", points=5.0)
    rep = engine.get_reputation("agent-1")
    assert rep.tier == ReputationTier.UNTRUSTED


def test_endorse(engine):
    endorsement = engine.endorse("agent-a", "agent-b", weight=2.0)
    assert endorsement.from_agent == "agent-a"
    assert endorsement.to_agent == "agent-b"
    rep = engine.get_reputation("agent-b")
    assert rep.score > 50.0
    assert rep.total_endorsements == 1


def test_warn(engine):
    engine.warn("agent-1", reason="suspicious behavior")
    rep = engine.get_reputation("agent-1")
    assert rep.score < 50.0


def test_apply_decay(engine):
    engine.record_success("agent-1", points=30.0)
    affected = engine.apply_decay()
    assert affected == 1
    rep = engine.get_reputation("agent-1")
    assert rep.score < 80.0


def test_decay_does_not_affect_below_50(engine):
    engine.record_failure("agent-1", points=10.0)
    affected = engine.apply_decay()
    assert affected == 0


def test_check_permission_allowed(engine):
    engine.set_policy("deploy", min_score=30.0)
    assert engine.check_permission("agent-1", "deploy") is True


def test_check_permission_denied(engine):
    engine.set_policy("deploy", min_score=80.0)
    assert engine.check_permission("agent-1", "deploy") is False


def test_check_permission_no_policy(engine):
    assert engine.check_permission("agent-1", "anything") is True


def test_check_permission_tier_required(engine):
    engine.set_policy("admin", required_tier=ReputationTier.ELITE)
    assert engine.check_permission("agent-1", "admin") is False


def test_get_events_by_agent(engine):
    engine.record_success("a")
    engine.record_success("b")
    events = engine.get_events(agent_id="a")
    assert len(events) == 1


def test_get_events_by_kind(engine):
    engine.record_success("a")
    engine.record_failure("a")
    events = engine.get_events(kind=FeedbackKind.PENALTY)
    assert len(events) == 1


def test_get_endorsements_to_agent(engine):
    engine.endorse("a", "b")
    engine.endorse("c", "b")
    engine.endorse("a", "d")
    endorsements = engine.get_endorsements(to_agent="b")
    assert len(endorsements) == 2


def test_get_endorsements_from_agent(engine):
    engine.endorse("a", "b")
    engine.endorse("a", "c")
    endorsements = engine.get_endorsements(from_agent="a")
    assert len(endorsements) == 2


def test_leaderboard(engine):
    engine.record_success("top", points=40.0)
    engine.record_success("mid", points=10.0)
    engine.record_failure("low", points=20.0)
    board = engine.get_leaderboard(top_n=2)
    assert len(board) == 2
    assert board[0].score > board[1].score


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_agents == 0
    assert stats.total_events == 0


def test_stats_populated(engine):
    engine.record_success("a", points=10.0)
    engine.record_failure("b", points=5.0)
    engine.endorse("a", "b")
    stats = engine.get_stats()
    assert stats.total_agents == 2
    assert stats.total_events >= 3
    assert stats.total_endorsements == 1
    assert stats.avg_score > 0


def test_failure_resets_streak(engine):
    engine.record_success("a")
    engine.record_success("a")
    engine.record_failure("a")
    rep = engine.get_reputation("a")
    assert rep.streak == 0
