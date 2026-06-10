"""Tests for delegation engine with hierarchical task delegation."""

from __future__ import annotations

import pytest

from reins.delegation import (
    AgentProfile,
    Capability,
    DelegationEngine,
    DelegationPolicy,
    DelegationRecord,
    DelegationStats,
    DelegationStatus,
    DelegationTask,
    EscalationReason,
)


@pytest.fixture
def engine() -> DelegationEngine:
    return DelegationEngine(policy=DelegationPolicy.FLEXIBLE)


@pytest.fixture
def agent_a() -> AgentProfile:
    return AgentProfile(
        agent_id="agent-a",
        capabilities=(Capability(name="coding", level=3.0), Capability(name="testing", level=2.0)),
        trust_score=0.9,
    )


@pytest.fixture
def agent_b() -> AgentProfile:
    return AgentProfile(
        agent_id="agent-b",
        capabilities=(Capability(name="coding", level=1.0),),
        trust_score=0.7,
    )


def _task(description="implement feature", required_caps=None):
    return DelegationTask(
        description=description,
        required_capabilities=tuple(required_caps or []),
    )


def test_register_agent(engine, agent_a):
    engine.register_agent(agent_a)
    assert engine.get_agent("agent-a") is not None


def test_get_agent_not_found(engine):
    assert engine.get_agent("nonexistent") is None


def test_unregister_agent(engine, agent_a):
    engine.register_agent(agent_a)
    assert engine.unregister_agent("agent-a")
    assert engine.get_agent("agent-a") is None


def test_unregister_agent_not_found(engine):
    assert not engine.unregister_agent("nonexistent")


def test_delegate_explicit(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    assert record is not None
    assert record.delegate == "agent-a"
    assert record.status == DelegationStatus.ASSIGNED


def test_delegate_auto_select(engine, agent_a, agent_b):
    engine.register_agent(agent_a)
    engine.register_agent(agent_b)
    task = _task()
    record = engine.delegate(task, "boss")
    assert record is not None
    assert record.delegate == "agent-a"  # higher trust


def test_delegate_capability_matching(engine, agent_a, agent_b):
    engine.register_agent(agent_a)
    engine.register_agent(agent_b)
    task = _task(required_caps=[Capability(name="testing", level=1.5)])
    record = engine.delegate(task, "boss")
    assert record is not None
    assert record.delegate == "agent-a"


def test_delegate_unavailable_agent(engine, agent_a):
    unavailable = AgentProfile(agent_id="agent-a", available=False)
    engine.register_agent(unavailable)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    assert record is None


def test_delegate_at_capacity(engine):
    full = AgentProfile(agent_id="full", max_concurrent=2, current_load=2)
    engine.register_agent(full)
    task = _task()
    record = engine.delegate(task, "boss", delegate="full")
    assert record is None


def test_delegate_no_agents(engine):
    task = _task()
    assert engine.delegate(task, "boss") is None


def test_complete_delegation(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    completed = engine.complete(record.record_id, result={"output": "done"})
    assert completed is not None
    assert completed.status == DelegationStatus.COMPLETED
    assert completed.result == {"output": "done"}
    assert completed.completed_at is not None


def test_complete_not_found(engine):
    assert engine.complete("nonexistent") is None


def test_complete_already_completed(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    engine.complete(record.record_id)
    assert engine.complete(record.record_id) is None


def test_fail_delegation(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    failed = engine.fail(record.record_id, reason=EscalationReason.TIMEOUT)
    assert failed is not None
    assert failed.status == DelegationStatus.FAILED
    assert failed.escalation_reason == EscalationReason.TIMEOUT


def test_fail_not_found(engine):
    assert engine.fail("nonexistent") is None


def test_escalate_delegation(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    escalated = engine.escalate(record.record_id, EscalationReason.COMPLEXITY_EXCEEDED)
    assert escalated is not None
    assert escalated.status == DelegationStatus.ESCALATED
    assert escalated.escalation_reason == EscalationReason.COMPLEXITY_EXCEEDED


def test_escalate_not_found(engine):
    assert engine.escalate("nonexistent", EscalationReason.TIMEOUT) is None


def test_revoke_delegation(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    assert engine.revoke(record.record_id)
    records = engine.get_records(status=DelegationStatus.REVOKED)
    assert len(records) == 1


def test_revoke_not_found(engine):
    assert not engine.revoke("nonexistent")


def test_revoke_completed(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    engine.complete(record.record_id)
    assert not engine.revoke(record.record_id)


def test_load_tracking(engine, agent_a):
    engine.register_agent(agent_a)
    task = _task()
    record = engine.delegate(task, "boss", delegate="agent-a")
    agent = engine.get_agent("agent-a")
    assert agent.current_load == 1
    engine.complete(record.record_id)
    agent = engine.get_agent("agent-a")
    assert agent.current_load == 0


def test_get_records_by_task(engine, agent_a):
    engine.register_agent(agent_a)
    t1 = _task(description="task 1")
    t2 = _task(description="task 2")
    engine.delegate(t1, "boss", delegate="agent-a")
    engine.delegate(t2, "boss", delegate="agent-a")
    records = engine.get_records(task_id=t1.task_id)
    assert len(records) == 1


def test_get_records_by_delegate(engine, agent_a, agent_b):
    engine.register_agent(agent_a)
    engine.register_agent(agent_b)
    task = _task()
    engine.delegate(task, "boss", delegate="agent-a")
    engine.delegate(_task(), "boss", delegate="agent-b")
    records = engine.get_records(delegate="agent-a")
    assert len(records) == 1


def test_get_records_by_status(engine, agent_a):
    engine.register_agent(agent_a)
    r1 = engine.delegate(_task(), "boss", delegate="agent-a")
    r2 = engine.delegate(_task(), "boss", delegate="agent-a")
    engine.complete(r1.record_id)
    records = engine.get_records(status=DelegationStatus.COMPLETED)
    assert len(records) == 1


def test_find_capable_agents(engine, agent_a, agent_b):
    engine.register_agent(agent_a)
    engine.register_agent(agent_b)
    task = _task(required_caps=[Capability(name="testing", level=1.0)])
    capable = engine.find_capable_agents(task)
    assert len(capable) == 1
    assert capable[0].agent_id == "agent-a"


def test_find_capable_agents_no_requirements(engine, agent_a, agent_b):
    engine.register_agent(agent_a)
    engine.register_agent(agent_b)
    task = _task()
    capable = engine.find_capable_agents(task)
    assert len(capable) == 2


def test_round_robin_policy():
    eng = DelegationEngine(policy=DelegationPolicy.ROUND_ROBIN)
    eng.register_agent(AgentProfile(agent_id="a", trust_score=0.5))
    eng.register_agent(AgentProfile(agent_id="b", trust_score=0.9))
    delegates = set()
    for _ in range(4):
        record = eng.delegate(_task(), "boss")
        if record:
            delegates.add(record.delegate)
            eng.complete(record.record_id)
    assert len(delegates) == 2


def test_stats_empty():
    eng = DelegationEngine()
    stats = eng.get_stats()
    assert stats.total_delegations == 0
    assert stats.success_rate == 0.0


def test_stats_with_data(engine, agent_a):
    engine.register_agent(agent_a)
    r1 = engine.delegate(_task(), "boss", delegate="agent-a")
    r2 = engine.delegate(_task(), "boss", delegate="agent-a")
    engine.complete(r1.record_id)
    engine.fail(r2.record_id)
    stats = engine.get_stats()
    assert stats.total_delegations == 2
    assert stats.completed == 1
    assert stats.failed == 1
    assert stats.success_rate == pytest.approx(0.5)
    assert stats.agents_registered == 1
