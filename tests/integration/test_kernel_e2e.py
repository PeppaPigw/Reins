"""End-to-end integration: full kernel lifecycle with journal, bus, pipeline, and mesh."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from reins.event_bus import EventBus
from reins.identity import IdentityProvider, TrustLevel
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor
from reins.policy_dsl import ConditionOp, PolicyDSLEngine, PolicyScope, RuleEffect
from reins.reactive_mesh import ReactionKind, ReactiveMesh, TriggerCondition
from reins.resource_accounting import ResourceAccountant, ResourceKind
from reins.safety_pipeline import (
    PipelineConfig,
    PipelineMode,
    PipelineStage,
    SafetyPipeline,
    StageVerdict,
)
from reins.safety_pipeline.adapters import (
    make_identity_stage,
    make_policy_stage,
    make_resource_stage,
)


@pytest.fixture
def kernel_runtime(tmp_path):
    """Full kernel runtime with journal persistence."""
    journal = EventJournal(tmp_path / "journal")
    bus = EventBus()

    identity = IdentityProvider()
    identity.register_identity("worker-1", display_name="Worker")
    identity.elevate_trust("worker-1", TrustLevel.VERIFIED)

    accountant = ResourceAccountant()
    accountant.set_quota("worker-1", ResourceKind.API_CALLS, limit=5.0)

    policy = PolicyDSLEngine()
    policy.add_rule(name="no-exec", effect=RuleEffect.DENY, scope=PolicyScope.ACTION,
                    conditions=[{"field": "action", "op": ConditionOp.EQUALS, "value": "exec"}])

    config = PipelineConfig(
        stages=[PipelineStage.IDENTITY, PipelineStage.RESOURCE_CHECK, PipelineStage.POLICY],
        mode=PipelineMode.STRICT,
    )
    pipeline = SafetyPipeline(config)
    pipeline.register_stage(PipelineStage.IDENTITY, make_identity_stage(identity))
    pipeline.register_stage(PipelineStage.RESOURCE_CHECK, make_resource_stage(accountant))
    pipeline.register_stage(PipelineStage.POLICY, make_policy_stage(policy))

    mesh = ReactiveMesh(bus)
    mesh.add_rule("quarantine-denied", TriggerCondition.EVENT_MATCH,
                  "safety.denied", ReactionKind.QUARANTINE, cooldown_seconds=0.0)

    def on_pipeline_event(event):
        if event.verdict == StageVerdict.FAIL:
            bus.publish_sync("safety.denied", event.agent_id,
                             {"agent_id": event.agent_id})

    pipeline.add_listener(on_pipeline_event)

    return {
        "journal": journal,
        "bus": bus,
        "pipeline": pipeline,
        "mesh": mesh,
        "identity": identity,
        "accountant": accountant,
    }


@pytest.mark.asyncio
async def test_full_lifecycle_pass(kernel_runtime):
    """Agent registers, acts safely, passes pipeline, journal records it."""
    journal = kernel_runtime["journal"]
    pipeline = kernel_runtime["pipeline"]

    result = await pipeline.evaluate("worker-1", {
        "agent_id": "worker-1", "action": "read",
    })
    assert result.final_verdict == StageVerdict.PASS

    event = EventEnvelope(
        run_id="run-001", actor=Actor.runtime, type="safety.evaluated",
        payload={"agent_id": "worker-1", "verdict": "pass"},
    )
    stored = await journal.append(event)
    assert stored.seq == 1

    events = []
    async for e in journal.read_from("run-001"):
        events.append(e)
    assert len(events) == 1
    assert events[0].payload["verdict"] == "pass"


@pytest.mark.asyncio
async def test_full_lifecycle_deny_and_quarantine(kernel_runtime):
    """Unknown agent gets denied, event fires, mesh quarantines."""
    pipeline = kernel_runtime["pipeline"]
    mesh = kernel_runtime["mesh"]
    journal = kernel_runtime["journal"]

    result = await pipeline.evaluate("intruder", {
        "agent_id": "intruder", "action": "read",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert mesh.is_quarantined("intruder")

    event = EventEnvelope(
        run_id="run-002", actor=Actor.policy, type="safety.denied",
        payload={"agent_id": "intruder", "reason": "identity_failed"},
    )
    stored = await journal.append(event)
    assert stored.seq == 1


@pytest.mark.asyncio
async def test_resource_exhaustion_lifecycle(kernel_runtime):
    """Agent exhausts resources, gets denied, mesh reacts."""
    pipeline = kernel_runtime["pipeline"]
    accountant = kernel_runtime["accountant"]
    mesh = kernel_runtime["mesh"]

    accountant.allocate("worker-1", ResourceKind.API_CALLS, 5.0)
    result = await pipeline.evaluate("worker-1", {
        "agent_id": "worker-1", "action": "read",
        "resource_kind": ResourceKind.API_CALLS, "resource_amount": 1.0,
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert mesh.is_quarantined("worker-1")


@pytest.mark.asyncio
async def test_policy_violation_lifecycle(kernel_runtime):
    """Agent tries forbidden action, gets denied and quarantined."""
    pipeline = kernel_runtime["pipeline"]
    mesh = kernel_runtime["mesh"]

    result = await pipeline.evaluate("worker-1", {
        "agent_id": "worker-1", "action": "exec",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert mesh.is_quarantined("worker-1")


@pytest.mark.asyncio
async def test_journal_preserves_event_ordering(kernel_runtime):
    """Multiple events maintain sequence ordering."""
    journal = kernel_runtime["journal"]

    for i in range(5):
        event = EventEnvelope(
            run_id="run-seq", actor=Actor.runtime, type="tick",
            payload={"i": i},
        )
        await journal.append(event)

    events = []
    async for e in journal.read_from("run-seq"):
        events.append(e)
    assert len(events) == 5
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_bus_replay_captures_safety_events(kernel_runtime):
    """Event bus replay shows all safety events that flowed through."""
    pipeline = kernel_runtime["pipeline"]
    bus = kernel_runtime["bus"]

    await pipeline.evaluate("worker-1", {"agent_id": "worker-1", "action": "read"})
    await pipeline.evaluate("bad", {"agent_id": "bad", "action": "read"})

    all_events = bus.replay("safety.*")
    denied = [e for e in all_events if e.topic == "safety.denied"]
    assert len(denied) >= 1
    assert any(e.payload.get("agent_id") == "bad" for e in denied)


@pytest.mark.asyncio
async def test_mesh_stats_after_lifecycle(kernel_runtime):
    """Mesh stats reflect all reactions fired during lifecycle."""
    pipeline = kernel_runtime["pipeline"]
    mesh = kernel_runtime["mesh"]

    await pipeline.evaluate("a", {"agent_id": "a", "action": "x"})
    await pipeline.evaluate("b", {"agent_id": "b", "action": "x"})

    stats = mesh.get_stats()
    assert stats.total_reactions >= 2
    assert stats.agents_quarantined >= 2
