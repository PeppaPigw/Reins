"""Tests for Safety Quorum — consensus-based escalation resolution."""

from __future__ import annotations

import pytest

from reins.consensus import ConsensusProtocol
from reins.event_bus import EventBus
from reins.kernel.safety_quorum import SafetyQuorum
from reins.reactive_mesh import ReactionKind, ReactiveMesh, TriggerCondition
from reins.reactive_mesh.types import Reaction


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def quorum(bus):
    q = SafetyQuorum(bus, protocol=ConsensusProtocol.MAJORITY, quorum=0.5)
    q.register_voter("safety-agent-1")
    q.register_voter("safety-agent-2")
    q.register_voter("safety-agent-3")
    return q


def test_propose_and_approve(bus, quorum):
    pid = quorum.propose_action("agent-x", "deploy_prod")
    quorum.vote("safety-agent-1", pid, approve=True)
    quorum.vote("safety-agent-2", pid, approve=True)
    decision = quorum.resolve(pid)
    assert decision is not None
    assert decision.accepted
    assert decision.votes_for == 2


def test_propose_and_reject(bus, quorum):
    pid = quorum.propose_action("agent-x", "delete_db")
    quorum.vote("safety-agent-1", pid, approve=False)
    quorum.vote("safety-agent-2", pid, approve=False)
    decision = quorum.resolve(pid)
    assert decision is not None
    assert not decision.accepted
    assert decision.votes_against == 2


def test_quorum_not_met(bus, quorum):
    q = SafetyQuorum(bus, protocol=ConsensusProtocol.MAJORITY, quorum=0.8)
    q.register_voter("v1")
    q.register_voter("v2")
    q.register_voter("v3")
    pid = q.propose_action("agent-x", "risky")
    q.vote("v1", pid, approve=True)
    decision = q.resolve(pid)
    assert decision is not None
    assert not decision.quorum_met


def test_handle_escalation(bus, quorum):
    reaction = Reaction(
        rule_id="r1", rule_name="esc", kind=ReactionKind.ESCALATE,
        trigger_event_id="ev1", agent_id="agent-y",
        payload={"action": "modify_policy"},
    )
    pid = quorum.handle_escalation(reaction)
    quorum.vote("safety-agent-1", pid, approve=True)
    quorum.vote("safety-agent-2", pid, approve=True)
    decision = quorum.resolve(pid)
    assert decision.accepted


def test_bus_events_emitted(bus, quorum):
    pid = quorum.propose_action("agent-x", "act")
    quorum.vote("safety-agent-1", pid, approve=True)
    quorum.vote("safety-agent-2", pid, approve=True)
    quorum.resolve(pid)
    proposed = bus.replay("quorum.proposed")
    accepted = bus.replay("quorum.accepted")
    assert len(proposed) == 1
    assert len(accepted) == 1


def test_duplicate_vote_rejected(bus, quorum):
    pid = quorum.propose_action("agent-x", "act")
    assert quorum.vote("safety-agent-1", pid, approve=True)
    assert not quorum.vote("safety-agent-1", pid, approve=False)


def test_unregistered_voter_rejected(bus, quorum):
    pid = quorum.propose_action("agent-x", "act")
    assert not quorum.vote("unknown-voter", pid, approve=True)


def test_unanimous_protocol(bus):
    q = SafetyQuorum(bus, protocol=ConsensusProtocol.UNANIMOUS, quorum=0.5)
    q.register_voter("v1")
    q.register_voter("v2")
    q.register_voter("v3")
    pid = q.propose_action("agent-x", "critical")
    q.vote("v1", pid, approve=True)
    q.vote("v2", pid, approve=True)
    q.vote("v3", pid, approve=False)
    decision = q.resolve(pid)
    assert not decision.accepted


def test_full_mesh_to_quorum_flow(bus):
    """End-to-end: mesh escalates → quorum collects votes → decision made."""
    mesh = ReactiveMesh(bus)
    quorum = SafetyQuorum(bus, protocol=ConsensusProtocol.MAJORITY)
    quorum.register_voter("s1")
    quorum.register_voter("s2")

    proposals = []
    mesh.on_reaction(ReactionKind.ESCALATE, lambda r: proposals.append(quorum.handle_escalation(r)))
    mesh.add_rule("esc-risky", TriggerCondition.EVENT_MATCH,
                  "action.risky", ReactionKind.ESCALATE, cooldown_seconds=0.0)

    bus.publish_sync("action.risky", "agent-z", {"agent_id": "agent-z", "action": "rm -rf"})
    assert len(proposals) == 1

    quorum.vote("s1", proposals[0], approve=False)
    quorum.vote("s2", proposals[0], approve=False)
    decision = quorum.resolve(proposals[0])
    assert not decision.accepted
    rejected = bus.replay("quorum.rejected")
    assert len(rejected) == 1
