"""Tests for KernelRuntime assembly and lifecycle."""

from __future__ import annotations

import pytest

from reins.identity import IdentityProvider, TrustLevel
from reins.kernel.runtime import KernelRuntime, RuntimeConfig
from reins.policy_dsl import ConditionOp, PolicyDSLEngine, PolicyScope, RuleEffect
from reins.reactive_mesh import ReactionKind, TriggerCondition
from reins.resource_accounting import ResourceAccountant, ResourceKind
from reins.safety_pipeline import PipelineStage, StageVerdict
from reins.safety_pipeline.adapters import (
    make_identity_stage,
    make_policy_stage,
    make_resource_stage,
)


@pytest.fixture
def runtime():
    rt = KernelRuntime()

    identity = IdentityProvider()
    identity.register_identity("agent-1", display_name="Agent")
    identity.elevate_trust("agent-1", TrustLevel.VERIFIED)

    accountant = ResourceAccountant()
    accountant.set_quota("agent-1", ResourceKind.API_CALLS, limit=10.0)

    policy = PolicyDSLEngine()
    policy.add_rule(name="no-delete", effect=RuleEffect.DENY, scope=PolicyScope.ACTION,
                    conditions=[{"field": "action", "op": ConditionOp.EQUALS, "value": "delete"}])

    rt.pipeline.register_stage(PipelineStage.IDENTITY, make_identity_stage(identity))
    rt.pipeline.register_stage(PipelineStage.RESOURCE_CHECK, make_resource_stage(accountant))
    rt.pipeline.register_stage(PipelineStage.POLICY, make_policy_stage(policy))

    rt.mesh.add_rule("quarantine-denied", TriggerCondition.EVENT_MATCH,
                     "safety.denied", ReactionKind.QUARANTINE, cooldown_seconds=0.0)

    rt.boot()
    return rt


@pytest.mark.asyncio
async def test_boot_lifecycle(runtime):
    assert runtime.is_booted
    events = runtime.bus.replay("kernel.booted")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_shutdown(runtime):
    runtime.shutdown()
    assert not runtime.is_booted
    events = runtime.bus.replay("kernel.shutdown")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_evaluate_pass(runtime):
    result = await runtime.evaluate("agent-1", {"agent_id": "agent-1", "action": "read"})
    assert result.final_verdict == StageVerdict.PASS
    passed = runtime.bus.replay("safety.passed")
    assert len(passed) == 1


@pytest.mark.asyncio
async def test_evaluate_deny_triggers_quarantine(runtime):
    result = await runtime.evaluate("unknown", {"agent_id": "unknown", "action": "read"})
    assert result.final_verdict == StageVerdict.FAIL
    assert runtime.mesh.is_quarantined("unknown")


@pytest.mark.asyncio
async def test_quarantined_agent_blocked_immediately(runtime):
    await runtime.evaluate("rogue", {"agent_id": "rogue", "action": "x"})
    assert runtime.mesh.is_quarantined("rogue")

    result = await runtime.evaluate("rogue", {"agent_id": "rogue", "action": "read"})
    assert result.final_verdict == StageVerdict.FAIL
    blocked = runtime.bus.replay("safety.blocked")
    assert len(blocked) == 1


@pytest.mark.asyncio
async def test_policy_violation_quarantines(runtime):
    result = await runtime.evaluate("agent-1", {"agent_id": "agent-1", "action": "delete"})
    assert result.final_verdict == StageVerdict.FAIL
    assert runtime.mesh.is_quarantined("agent-1")


@pytest.mark.asyncio
async def test_boot_hooks():
    called = []
    rt = KernelRuntime()
    rt.on_boot(lambda: called.append("booted"))
    rt.boot()
    assert called == ["booted"]


@pytest.mark.asyncio
async def test_shutdown_hooks():
    called = []
    rt = KernelRuntime()
    rt.on_shutdown(lambda: called.append("down"))
    rt.boot()
    rt.shutdown()
    assert called == ["down"]


@pytest.mark.asyncio
async def test_bus_captures_all_events(runtime):
    await runtime.evaluate("agent-1", {"agent_id": "agent-1", "action": "read"})
    await runtime.evaluate("bad", {"agent_id": "bad", "action": "x"})
    all_events = runtime.bus.replay("safety.*")
    assert len(all_events) >= 2
