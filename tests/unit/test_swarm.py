"""Tests for swarm intelligence with emergent coordination."""

from __future__ import annotations

import pytest

from reins.swarm import (
    ConsensusMethod,
    PheromoneTrail,
    SignalKind,
    SwarmAgent,
    SwarmDecision,
    SwarmEngine,
    SwarmRole,
    SwarmSignal,
    SwarmStats,
    SwarmTask,
)


@pytest.fixture
def engine() -> SwarmEngine:
    return SwarmEngine()


@pytest.fixture
def populated_swarm(engine) -> SwarmEngine:
    engine.register_agent("a1", role=SwarmRole.SCOUT, position=(0.0, 0.0))
    engine.register_agent("a2", role=SwarmRole.WORKER, position=(1.0, 0.0))
    engine.register_agent("a3", role=SwarmRole.WORKER, position=(0.0, 1.0))
    return engine


def test_register_agent(engine):
    agent = engine.register_agent("agent-1", role=SwarmRole.SCOUT)
    assert agent.agent_id == "agent-1"
    assert agent.role == SwarmRole.SCOUT


def test_get_agent(engine):
    engine.register_agent("agent-1")
    assert engine.get_agent("agent-1") is not None
    assert engine.get_agent("nonexistent") is None


def test_update_agent_role(engine):
    engine.register_agent("agent-1", role=SwarmRole.IDLE)
    updated = engine.update_agent("agent-1", role=SwarmRole.LEADER)
    assert updated.role == SwarmRole.LEADER


def test_update_agent_position(engine):
    engine.register_agent("agent-1", position=(0.0, 0.0))
    updated = engine.update_agent("agent-1", position=(5.0, 3.0))
    assert updated.position == (5.0, 3.0)


def test_update_agent_not_found(engine):
    assert engine.update_agent("nonexistent", role=SwarmRole.WORKER) is None


def test_emit_signal(engine):
    engine.register_agent("a1")
    signal = engine.emit_signal("a1", SignalKind.PHEROMONE, intensity=0.8)
    assert signal.kind == SignalKind.PHEROMONE
    assert signal.intensity == 0.8


def test_get_signals_by_kind(engine):
    engine.emit_signal("a1", SignalKind.PHEROMONE)
    engine.emit_signal("a1", SignalKind.ALARM)
    signals = engine.get_signals(kind=SignalKind.ALARM)
    assert len(signals) == 1
    assert signals[0].kind == SignalKind.ALARM


def test_get_signals_by_target(engine):
    engine.emit_signal("a1", SignalKind.BROADCAST, target="a2")
    engine.emit_signal("a1", SignalKind.BROADCAST, target="a3")
    signals = engine.get_signals(target="a2")
    assert len(signals) == 1


def test_get_signals_min_intensity(engine):
    engine.emit_signal("a1", SignalKind.PHEROMONE, intensity=0.5)
    engine.emit_signal("a1", SignalKind.PHEROMONE, intensity=0.1)
    signals = engine.get_signals(min_intensity=0.3)
    assert len(signals) == 1


def test_deposit_pheromone(engine):
    trail = engine.deposit_pheromone("a1", "resource-x", intensity=2.0)
    assert trail.resource == "resource-x"
    assert trail.intensity == 2.0


def test_deposit_pheromone_stacks(engine):
    engine.deposit_pheromone("a1", "resource-x", intensity=2.0)
    trail = engine.deposit_pheromone("a2", "resource-x", intensity=3.0)
    assert trail.intensity == 5.0


def test_deposit_pheromone_caps_at_10(engine):
    engine.deposit_pheromone("a1", "resource-x", intensity=8.0)
    trail = engine.deposit_pheromone("a2", "resource-x", intensity=5.0)
    assert trail.intensity == 10.0


def test_get_trail(engine):
    engine.deposit_pheromone("a1", "res")
    assert engine.get_trail("res") is not None
    assert engine.get_trail("nonexistent") is None


def test_get_strongest_trails(engine):
    engine.deposit_pheromone("a1", "weak", intensity=0.5)
    engine.deposit_pheromone("a1", "strong", intensity=5.0)
    engine.deposit_pheromone("a1", "medium", intensity=2.0)
    trails = engine.get_strongest_trails(top_n=2)
    assert len(trails) == 2
    assert trails[0].intensity >= trails[1].intensity


def test_decay_signals(engine):
    engine.emit_signal("a1", SignalKind.PHEROMONE, intensity=1.0, decay_rate=0.5)
    removed = engine.decay_signals()
    assert removed == 0
    signals = engine.get_signals()
    assert signals[0].intensity == pytest.approx(0.5)


def test_decay_signals_removes_weak(engine):
    engine.emit_signal("a1", SignalKind.PHEROMONE, intensity=0.01, decay_rate=0.9)
    removed = engine.decay_signals()
    assert removed == 1


def test_decay_trails(engine):
    engine.deposit_pheromone("a1", "res", intensity=1.0, decay_rate=0.5)
    removed = engine.decay_trails()
    assert removed == 0
    trail = engine.get_trail("res")
    assert trail.intensity == pytest.approx(0.5)


def test_decay_trails_removes_weak(engine):
    engine.deposit_pheromone("a1", "res", intensity=0.005, decay_rate=0.9)
    removed = engine.decay_trails()
    assert removed == 1


def test_propose_decision(engine):
    decision = engine.propose_decision("migrate to v2", quorum=3)
    assert decision.proposal == "migrate to v2"
    assert not decision.resolved


def test_vote_majority(engine):
    decision = engine.propose_decision("go", quorum=3)
    engine.vote(decision.decision_id, True)
    engine.vote(decision.decision_id, True)
    result = engine.vote(decision.decision_id, False)
    assert result.resolved is True
    assert result.outcome is True


def test_vote_majority_rejected(engine):
    decision = engine.propose_decision("go", quorum=3)
    engine.vote(decision.decision_id, False)
    engine.vote(decision.decision_id, False)
    result = engine.vote(decision.decision_id, True)
    assert result.resolved is True
    assert result.outcome is False


def test_vote_quorum_sensing(engine):
    decision = engine.propose_decision("go", method=ConsensusMethod.QUORUM_SENSING, quorum=2)
    engine.vote(decision.decision_id, True)
    result = engine.vote(decision.decision_id, True)
    assert result.resolved is True
    assert result.outcome is True


def test_vote_on_resolved_noop(engine):
    decision = engine.propose_decision("go", quorum=1)
    engine.vote(decision.decision_id, True)
    result = engine.vote(decision.decision_id, False)
    assert result.outcome is True


def test_get_decision(engine):
    decision = engine.propose_decision("test")
    assert engine.get_decision(decision.decision_id) is not None
    assert engine.get_decision("nonexistent") is None


def test_create_task(engine):
    task = engine.create_task("build feature", required_agents=2)
    assert task.description == "build feature"
    assert task.required_agents == 2


def test_assign_task(engine):
    task = engine.create_task("work")
    result = engine.assign_task(task.task_id, "a1")
    assert "a1" in result.assigned_agents


def test_assign_task_idempotent(engine):
    task = engine.create_task("work")
    engine.assign_task(task.task_id, "a1")
    result = engine.assign_task(task.task_id, "a1")
    assert len(result.assigned_agents) == 1


def test_complete_task(engine):
    task = engine.create_task("work")
    result = engine.complete_task(task.task_id)
    assert result.completed is True


def test_complete_task_not_found(engine):
    assert engine.complete_task("nonexistent") is None


def test_get_unassigned_tasks(engine):
    engine.create_task("t1", required_agents=2)
    t2 = engine.create_task("t2", required_agents=1)
    engine.assign_task(t2.task_id, "a1")
    unassigned = engine.get_unassigned_tasks()
    assert len(unassigned) == 1


def test_compute_distance(populated_swarm):
    dist = populated_swarm.compute_distance("a1", "a2")
    assert dist == pytest.approx(1.0)


def test_compute_distance_no_position(engine):
    engine.register_agent("a1")
    engine.register_agent("a2")
    assert engine.compute_distance("a1", "a2") is None


def test_compute_distance_unknown_agent(engine):
    assert engine.compute_distance("a1", "a2") is None


def test_get_neighbors(populated_swarm):
    neighbors = populated_swarm.get_neighbors("a1", radius=1.5)
    assert len(neighbors) == 2


def test_get_neighbors_radius_filter(populated_swarm):
    neighbors = populated_swarm.get_neighbors("a1", radius=0.5)
    assert len(neighbors) == 0


def test_auto_assign_roles(engine):
    engine.register_agent("a1", role=SwarmRole.IDLE)
    engine.register_agent("a2", role=SwarmRole.IDLE)
    engine.register_agent("a3", role=SwarmRole.IDLE)
    engine.create_task("work")
    assignments = engine.auto_assign_roles()
    assert SwarmRole.SCOUT in assignments.values()
    assert SwarmRole.WORKER in assignments.values()


def test_auto_assign_roles_empty(engine):
    assignments = engine.auto_assign_roles()
    assert assignments == {}


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_agents == 0
    assert stats.active_signals == 0


def test_stats_populated(populated_swarm):
    populated_swarm.emit_signal("a1", SignalKind.BROADCAST)
    populated_swarm.deposit_pheromone("a1", "res")
    task = populated_swarm.create_task("work")
    populated_swarm.complete_task(task.task_id)
    decision = populated_swarm.propose_decision("go", quorum=1)
    populated_swarm.vote(decision.decision_id, True)
    stats = populated_swarm.get_stats()
    assert stats.total_agents == 3
    assert stats.active_signals == 1
    assert stats.active_trails == 1
    assert stats.decisions_made == 1
    assert stats.tasks_completed == 1
    assert stats.avg_energy == pytest.approx(1.0)
