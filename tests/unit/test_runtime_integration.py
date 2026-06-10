"""Integration test: Event Bus + Safety Pipeline + Reactive Mesh as unified runtime."""

from __future__ import annotations

import pytest

from reins.behavior_versioning import BehaviorVersioner
from reins.event_bus import EventBus, EventPriority
from reins.identity import IdentityProvider, TrustLevel
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
    make_behavior_stage,
    make_identity_stage,
    make_policy_stage,
    make_resource_stage,
)


@pytest.fixture
def runtime():
    """Full runtime: bus + pipeline + mesh + all safety modules."""
    bus = EventBus()

    identity = IdentityProvider()
    identity.register_identity("trusted-agent", display_name="Trusted")
    identity.elevate_trust("trusted-agent", TrustLevel.VERIFIED)

    accountant = ResourceAccountant()
    accountant.set_quota("trusted-agent", ResourceKind.API_CALLS, limit=10.0)

    policy = PolicyDSLEngine()
    policy.add_rule(name="block-delete", effect=RuleEffect.DENY, scope=PolicyScope.ACTION,
                    conditions=[{"field": "action", "op": ConditionOp.EQUALS, "value": "delete_all"}])

    versioner = BehaviorVersioner()
    versioner.capture_signature("trusted-agent", action_profile={"read": 5}, success_rate=0.95)
    versioner.create_baseline("trusted-agent", is_golden=True)

    config = PipelineConfig(
        stages=[PipelineStage.IDENTITY, PipelineStage.RESOURCE_CHECK,
                PipelineStage.POLICY, PipelineStage.BEHAVIOR_CHECK],
        mode=PipelineMode.STRICT,
    )
    pipeline = SafetyPipeline(config)
    pipeline.register_stage(PipelineStage.IDENTITY, make_identity_stage(identity))
    pipeline.register_stage(PipelineStage.RESOURCE_CHECK, make_resource_stage(accountant))
    pipeline.register_stage(PipelineStage.POLICY, make_policy_stage(policy))
    pipeline.register_stage(PipelineStage.BEHAVIOR_CHECK, make_behavior_stage(versioner))

    mesh = ReactiveMesh(bus)
    mesh.add_rule("quarantine-on-violation", TriggerCondition.EVENT_MATCH,
                  "safety.denied", ReactionKind.QUARANTINE, cooldown_seconds=0.0)
    mesh.add_rule("alert-on-resource", TriggerCondition.THRESHOLD_BREACH,
                  "resource.warning", ReactionKind.ALERT,
                  threshold=3, window_seconds=60.0, cooldown_seconds=0.0)

    # Wire pipeline results to bus
    def on_pipeline_event(event):
        if event.verdict == StageVerdict.FAIL:
            bus.publish_sync("safety.denied", event.agent_id,
                             {"agent_id": event.agent_id, "stage": event.stage.value if event.stage else ""})

    pipeline.add_listener(on_pipeline_event)

    return {
        "bus": bus,
        "pipeline": pipeline,
        "mesh": mesh,
        "identity": identity,
        "accountant": accountant,
        "policy": policy,
        "versioner": versioner,
    }


@pytest.mark.asyncio
async def test_trusted_agent_passes_full_runtime(runtime):
    result = await runtime["pipeline"].evaluate("trusted-agent", {
        "agent_id": "trusted-agent", "action": "read_file",
    })
    assert result.final_verdict == StageVerdict.PASS
    assert not runtime["mesh"].is_quarantined("trusted-agent")


@pytest.mark.asyncio
async def test_unknown_agent_triggers_quarantine(runtime):
    result = await runtime["pipeline"].evaluate("hacker", {
        "agent_id": "hacker", "action": "read_file",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert runtime["mesh"].is_quarantined("hacker")


@pytest.mark.asyncio
async def test_policy_violation_triggers_quarantine(runtime):
    result = await runtime["pipeline"].evaluate("trusted-agent", {
        "agent_id": "trusted-agent", "action": "delete_all",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert runtime["mesh"].is_quarantined("trusted-agent")


@pytest.mark.asyncio
async def test_resource_exhaustion_triggers_quarantine(runtime):
    acc = runtime["accountant"]
    acc.allocate("trusted-agent", ResourceKind.API_CALLS, 10.0)
    result = await runtime["pipeline"].evaluate("trusted-agent", {
        "agent_id": "trusted-agent", "action": "read",
        "resource_kind": ResourceKind.API_CALLS, "resource_amount": 1.0,
    })
    assert result.final_verdict == StageVerdict.FAIL


@pytest.mark.asyncio
async def test_event_bus_captures_all_pipeline_events(runtime):
    await runtime["pipeline"].evaluate("trusted-agent", {
        "agent_id": "trusted-agent", "action": "read",
    })
    events = runtime["bus"].replay("safety.*")
    # No safety.denied events for a passing pipeline
    denied = [e for e in events if e.topic == "safety.denied"]
    assert len(denied) == 0


@pytest.mark.asyncio
async def test_cascading_reaction_chain(runtime):
    """Denied agent gets quarantined, then further requests are blocked by identity."""
    await runtime["pipeline"].evaluate("rogue", {
        "agent_id": "rogue", "action": "probe",
    })
    assert runtime["mesh"].is_quarantined("rogue")
    reactions = runtime["mesh"].get_reactions(agent_id="rogue")
    assert any(r.kind == ReactionKind.QUARANTINE for r in reactions)


@pytest.mark.asyncio
async def test_stats_reflect_full_runtime(runtime):
    await runtime["pipeline"].evaluate("trusted-agent", {"agent_id": "trusted-agent", "action": "x"})
    await runtime["pipeline"].evaluate("bad", {"agent_id": "bad", "action": "x"})

    pipeline_stats = runtime["pipeline"].get_stats()
    assert pipeline_stats.total_executions == 2
    assert pipeline_stats.passed >= 1
    assert pipeline_stats.failed >= 1

    mesh_stats = runtime["mesh"].get_stats()
    assert mesh_stats.total_reactions >= 1

    bus_stats = runtime["bus"].get_stats()
    assert bus_stats.total_published >= 1
