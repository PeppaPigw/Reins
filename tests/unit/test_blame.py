"""Tests for blame attribution engine."""

from __future__ import annotations

import pytest

from reins.blame import (
    AgentAction,
    BlameAssignment,
    BlameEngine,
    BlameLevel,
    BlameReport,
    BlameStats,
    FailureEvent,
    FailureKind,
)


@pytest.fixture
def engine() -> BlameEngine:
    return BlameEngine()


def test_record_action(engine):
    action = engine.record_action("agent-1", "file_write",
                                   effects=["modified config.yaml"])
    assert action.agent_id == "agent-1"
    assert action.success is True


def test_record_failed_action(engine):
    action = engine.record_action("agent-1", "api_call",
                                   success=False, error="timeout")
    assert action.success is False
    assert action.error == "timeout"


def test_record_failure(engine):
    failure = engine.record_failure(FailureKind.TIMEOUT, "agent-1",
                                    message="Request timed out after 30s")
    assert failure.kind == FailureKind.TIMEOUT
    assert failure.agent_id == "agent-1"


def test_analyze_simple_failure(engine):
    action = engine.record_action("agent-1", "db_query",
                                   success=False, error="connection refused")
    failure = engine.record_failure(FailureKind.ERROR, "agent-1",
                                    action_id=action.action_id)
    report = engine.analyze(failure.failure_id)
    assert report.root_cause_agent == "agent-1"
    assert len(report.assignments) >= 1
    assert report.assignments[0].level == BlameLevel.ROOT_CAUSE


def test_analyze_causal_chain(engine):
    a1 = engine.record_action("agent-a", "fetch_config", success=False,
                               error="network error")
    a2 = engine.record_action("agent-b", "process_data",
                               caused_by=a1.action_id, success=False,
                               error="missing config")
    failure = engine.record_failure(FailureKind.CASCADING, "agent-b",
                                    action_id=a2.action_id)
    report = engine.analyze(failure.failure_id)
    assert report.causal_depth >= 2
    levels = {a.agent_id: a.level for a in report.assignments}
    assert levels["agent-b"] == BlameLevel.ROOT_CAUSE
    assert levels["agent-a"] in (BlameLevel.CONTRIBUTING, BlameLevel.PROPAGATING)


def test_analyze_no_action_id(engine):
    engine.record_action("agent-x", "work", success=False, error="oops")
    failure = engine.record_failure(FailureKind.ERROR, "agent-x")
    report = engine.analyze(failure.failure_id)
    assert report.root_cause_agent == "agent-x"


def test_analyze_unknown_failure(engine):
    report = engine.analyze("nonexistent")
    assert report.root_cause_agent == ""
    assert report.assignments == []


def test_get_failures_filter(engine):
    engine.record_failure(FailureKind.TIMEOUT, "a")
    engine.record_failure(FailureKind.ERROR, "b")
    engine.record_failure(FailureKind.TIMEOUT, "a")
    assert len(engine.get_failures(agent_id="a")) == 2
    assert len(engine.get_failures(kind=FailureKind.ERROR)) == 1


def test_get_reports_filter(engine):
    a = engine.record_action("agent-1", "x", success=False, error="e")
    f = engine.record_failure(FailureKind.ERROR, "agent-1", action_id=a.action_id)
    engine.analyze(f.failure_id)
    assert len(engine.get_reports(agent_id="agent-1")) == 1
    assert len(engine.get_reports(agent_id="other")) == 0


def test_agent_blame_score(engine):
    a1 = engine.record_action("bad-agent", "x", success=False, error="e")
    f1 = engine.record_failure(FailureKind.ERROR, "bad-agent", action_id=a1.action_id)
    engine.analyze(f1.failure_id)

    a2 = engine.record_action("bad-agent", "y", success=False, error="e2")
    f2 = engine.record_failure(FailureKind.ERROR, "bad-agent", action_id=a2.action_id)
    engine.analyze(f2.failure_id)

    score = engine.get_agent_blame_score("bad-agent")
    assert score >= 1.5


def test_blame_score_zero_for_innocent(engine):
    assert engine.get_agent_blame_score("innocent") == 0.0


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_failures == 0
    assert stats.total_reports == 0


def test_stats_populated(engine):
    a = engine.record_action("a", "x", success=False, error="e")
    f = engine.record_failure(FailureKind.TIMEOUT, "a", action_id=a.action_id)
    engine.analyze(f.failure_id)
    stats = engine.get_stats()
    assert stats.total_failures == 1
    assert stats.total_reports == 1
    assert stats.by_failure_kind["timeout"] == 1
    assert "root_cause" in stats.by_blame_level


def test_all_failure_kinds(engine):
    for kind in FailureKind:
        engine.record_failure(kind, "agent")
    assert len(engine.get_failures()) == len(FailureKind)


def test_deep_causal_chain(engine):
    actions = []
    for i in range(5):
        caused_by = actions[-1].action_id if actions else ""
        a = engine.record_action(f"agent-{i}", f"step-{i}",
                                  caused_by=caused_by,
                                  success=(i < 4), error="fail" if i == 4 else "")
        actions.append(a)
    failure = engine.record_failure(FailureKind.CASCADING, "agent-4",
                                    action_id=actions[-1].action_id)
    report = engine.analyze(failure.failure_id)
    assert report.causal_depth >= 3
    assert len(report.assignments) >= 2


def test_confidence_decreases_with_depth(engine):
    a1 = engine.record_action("root", "init", success=False, error="e")
    a2 = engine.record_action("mid", "process", caused_by=a1.action_id,
                               success=False, error="e")
    a3 = engine.record_action("leaf", "output", caused_by=a2.action_id,
                               success=False, error="e")
    f = engine.record_failure(FailureKind.CASCADING, "leaf",
                              action_id=a3.action_id)
    report = engine.analyze(f.failure_id)
    confidences = [a.confidence for a in report.assignments]
    assert confidences == sorted(confidences, reverse=True)
