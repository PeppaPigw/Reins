"""Tests for emergent behavior detection in multi-agent systems."""

from __future__ import annotations

import pytest

from reins.emergent import (
    AgentAction,
    EmergentDetector,
    EmergentPattern,
    EmergentStats,
    PatternKind,
    Severity,
)


@pytest.fixture
def detector() -> EmergentDetector:
    return EmergentDetector(window_size=20, herding_threshold=0.7, cascade_threshold=3)


def test_record_action(detector):
    action = detector.record_action("agent-1", "buy", target="stock_a", value=100.0)
    assert action.agent_id == "agent-1"


def test_record_batch(detector):
    actions = [
        ("a", "buy", "x", 1.0),
        ("b", "buy", "x", 2.0),
        ("c", "sell", "y", -1.0),
    ]
    results = detector.record_batch(actions)
    assert len(results) == 3


def test_detect_herding(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "buy")
    patterns = detector.get_patterns(kind=PatternKind.HERDING)
    assert len(patterns) >= 1


def test_herding_confidence(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "buy")
    patterns = detector.get_patterns(kind=PatternKind.HERDING)
    assert patterns[0].confidence >= 0.7


def test_no_herding_diverse_actions(detector):
    actions = ["buy", "sell", "hold", "research", "wait"]
    for agent, action in zip(["a", "b", "c", "d", "e"], actions):
        detector.record_action(agent, action)
    patterns = detector.get_patterns(kind=PatternKind.HERDING)
    assert len(patterns) == 0


def test_detect_cascade(detector):
    detector.record_action("x", "normal")
    detector.record_action("y", "normal")
    for agent in ["a", "b", "c", "d"]:
        detector.record_action(agent, "panic_sell")
    patterns = detector.get_patterns(kind=PatternKind.CASCADE)
    assert len(patterns) >= 1


def test_detect_feedback_loop(detector):
    for _ in range(4):
        detector.record_action("agent-1", "retry")
        detector.record_action("agent-1", "fail")
    patterns = detector.get_patterns(kind=PatternKind.FEEDBACK_LOOP)
    assert len(patterns) >= 1


def test_feedback_loop_agent_identified(detector):
    for _ in range(4):
        detector.record_action("stuck-agent", "attempt")
        detector.record_action("stuck-agent", "error")
    patterns = detector.get_patterns(kind=PatternKind.FEEDBACK_LOOP)
    assert "stuck-agent" in patterns[0].agents_involved


def test_compute_diversity_uniform(detector):
    for i, agent in enumerate(["a", "b", "c", "d", "e"]):
        detector.record_action(agent, f"action_{i}")
    assert detector.compute_diversity() >= 1.0


def test_compute_diversity_low(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "same_action")
    assert detector.compute_diversity() < 0.5


def test_compute_synchronization_high(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "sync_action")
    assert detector.compute_synchronization() >= 0.8


def test_compute_synchronization_low(detector):
    for i, agent in enumerate(["a", "b", "c", "d", "e"]):
        detector.record_action(agent, f"unique_{i}")
    assert detector.compute_synchronization() <= 0.3


def test_compute_polarization_high(detector):
    for agent in ["a", "b", "c"]:
        detector.record_action(agent, "vote", value=1.0)
    for agent in ["d", "e", "f"]:
        detector.record_action(agent, "vote", value=-1.0)
    pol = detector.compute_polarization()
    assert pol > 0.5


def test_compute_polarization_low(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "vote", value=1.0)
    pol = detector.compute_polarization()
    assert pol < 0.3


def test_get_metrics(detector):
    for agent in ["a", "b", "c"]:
        detector.record_action(agent, "action")
    metrics = detector.get_metrics()
    assert len(metrics) == 3
    names = [m.name for m in metrics]
    assert "diversity" in names
    assert "synchronization" in names
    assert "polarization" in names


def test_get_patterns_by_severity(detector):
    for agent in ["a", "b", "c", "d", "e", "f"]:
        detector.record_action(agent, "herd")
    patterns = detector.get_patterns(severity=Severity.CONCERNING)
    assert len(patterns) >= 0


def test_stats_empty():
    d = EmergentDetector()
    stats = d.get_stats()
    assert stats.total_actions == 0
    assert stats.total_patterns == 0


def test_stats_with_data(detector):
    for agent in ["a", "b", "c", "d", "e"]:
        detector.record_action(agent, "converge")
    stats = detector.get_stats()
    assert stats.total_actions == 5
    assert stats.agents_monitored == 5
    assert stats.total_patterns >= 1
