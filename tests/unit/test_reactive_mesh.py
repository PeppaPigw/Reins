"""Tests for reactive safety mesh."""

from __future__ import annotations

import pytest

from reins.event_bus import EventBus
from reins.reactive_mesh import (
    ReactionKind,
    ReactiveMesh,
    TriggerCondition,
)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mesh(bus) -> ReactiveMesh:
    return ReactiveMesh(bus)


def test_event_match_fires_reaction(bus, mesh):
    mesh.add_rule("block-on-violation", TriggerCondition.EVENT_MATCH,
                  "safety.violation", ReactionKind.BLOCK)
    bus.publish_sync("safety.violation", "agent-1", {"agent_id": "agent-1"})
    reactions = mesh.get_reactions()
    assert len(reactions) == 1
    assert reactions[0].kind == ReactionKind.BLOCK


def test_no_match_no_reaction(bus, mesh):
    mesh.add_rule("block-on-violation", TriggerCondition.EVENT_MATCH,
                  "safety.violation", ReactionKind.BLOCK)
    bus.publish_sync("agent.started", "agent-1")
    assert len(mesh.get_reactions()) == 0


def test_quarantine(bus, mesh):
    mesh.add_rule("quarantine-bad", TriggerCondition.EVENT_MATCH,
                  "safety.critical", ReactionKind.QUARANTINE)
    bus.publish_sync("safety.critical", "agent-x", {"agent_id": "agent-x"})
    assert mesh.is_quarantined("agent-x")


def test_release_quarantine(bus, mesh):
    mesh.add_rule("q", TriggerCondition.EVENT_MATCH, "bad", ReactionKind.QUARANTINE)
    bus.publish_sync("bad", "a", {"agent_id": "a"})
    assert mesh.is_quarantined("a")
    assert mesh.release_quarantine("a")
    assert not mesh.is_quarantined("a")


def test_threshold_breach(bus, mesh):
    mesh.add_rule("rate-limit", TriggerCondition.THRESHOLD_BREACH,
                  "api.call", ReactionKind.THROTTLE,
                  threshold=3, window_seconds=60.0, cooldown_seconds=0.0)
    bus.publish_sync("api.call", "agent-1", {"agent_id": "agent-1"})
    bus.publish_sync("api.call", "agent-1", {"agent_id": "agent-1"})
    assert len(mesh.get_reactions()) == 0
    bus.publish_sync("api.call", "agent-1", {"agent_id": "agent-1"})
    assert len(mesh.get_reactions()) == 1
    assert mesh.get_reactions()[0].kind == ReactionKind.THROTTLE


def test_anomaly_trigger(bus, mesh):
    mesh.add_rule("anomaly-alert", TriggerCondition.ANOMALY,
                  "metrics.*", ReactionKind.ALERT, threshold=0.8, cooldown_seconds=0.0)
    bus.publish_sync("metrics.latency", "monitor", {"anomaly_score": 0.5})
    assert len(mesh.get_reactions()) == 0
    bus.publish_sync("metrics.latency", "monitor", {"anomaly_score": 0.9})
    assert len(mesh.get_reactions()) == 1


def test_cooldown(bus, mesh):
    mesh.add_rule("alert", TriggerCondition.EVENT_MATCH,
                  "error", ReactionKind.ALERT, cooldown_seconds=999.0)
    bus.publish_sync("error", "src", {"agent_id": "a"})
    bus.publish_sync("error", "src", {"agent_id": "a"})
    assert len(mesh.get_reactions()) == 1


def test_reaction_handler_callback(bus, mesh):
    received = []
    mesh.on_reaction(ReactionKind.ESCALATE, lambda r: received.append(r))
    mesh.add_rule("esc", TriggerCondition.EVENT_MATCH, "danger", ReactionKind.ESCALATE,
                  cooldown_seconds=0.0)
    bus.publish_sync("danger", "src", {"agent_id": "x"})
    assert len(received) == 1
    assert received[0].kind == ReactionKind.ESCALATE


def test_remove_rule(bus, mesh):
    rule = mesh.add_rule("r", TriggerCondition.EVENT_MATCH, "*", ReactionKind.BLOCK)
    assert mesh.remove_rule(rule.rule_id)
    bus.publish_sync("anything", "src")
    assert len(mesh.get_reactions()) == 0


def test_filter_reactions_by_agent(bus, mesh):
    mesh.add_rule("r", TriggerCondition.EVENT_MATCH, "*", ReactionKind.ALERT,
                  cooldown_seconds=0.0)
    bus.publish_sync("x", "src", {"agent_id": "a"})
    bus.publish_sync("x", "src", {"agent_id": "b"})
    assert len(mesh.get_reactions(agent_id="a")) == 1
    assert len(mesh.get_reactions(agent_id="b")) == 1


def test_filter_reactions_by_kind(bus, mesh):
    mesh.add_rule("r1", TriggerCondition.EVENT_MATCH, "a", ReactionKind.BLOCK,
                  cooldown_seconds=0.0)
    mesh.add_rule("r2", TriggerCondition.EVENT_MATCH, "b", ReactionKind.ALERT,
                  cooldown_seconds=0.0)
    bus.publish_sync("a", "src", {"agent_id": "x"})
    bus.publish_sync("b", "src", {"agent_id": "x"})
    assert len(mesh.get_reactions(kind=ReactionKind.BLOCK)) == 1
    assert len(mesh.get_reactions(kind=ReactionKind.ALERT)) == 1


def test_stats(bus, mesh):
    mesh.add_rule("r", TriggerCondition.EVENT_MATCH, "*", ReactionKind.QUARANTINE,
                  cooldown_seconds=0.0)
    bus.publish_sync("x", "src", {"agent_id": "a"})
    stats = mesh.get_stats()
    assert stats.total_rules == 1
    assert stats.total_reactions == 1
    assert stats.agents_quarantined == 1


def test_pattern_detected_trigger(bus, mesh):
    mesh.add_rule("pattern", TriggerCondition.PATTERN_DETECTED,
                  "behavior.*", ReactionKind.ROLLBACK, cooldown_seconds=0.0)
    bus.publish_sync("behavior.drift", "monitor", {"pattern_match": True, "agent_id": "a"})
    assert len(mesh.get_reactions()) == 1
    assert mesh.get_reactions()[0].kind == ReactionKind.ROLLBACK


def test_disabled_rule_does_not_fire(bus, mesh):
    rule = mesh.add_rule("r", TriggerCondition.EVENT_MATCH, "*", ReactionKind.BLOCK)
    mesh._rules[rule.rule_id] = rule.model_copy(update={"enabled": False})
    bus.publish_sync("x", "src")
    assert len(mesh.get_reactions()) == 0
