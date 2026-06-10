"""Integration test: full safety pipeline with real module adapters."""

from __future__ import annotations

import pytest

from reins.behavior_versioning import BehaviorVersioner
from reins.identity import IdentityProvider, TrustLevel
from reins.policy_dsl import ConditionOp, PolicyDSLEngine, PolicyScope, RuleEffect
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
def full_pipeline():
    identity = IdentityProvider()
    agent = identity.register_identity("agent-1", display_name="Worker")
    identity.issue_credential(agent.agent_id, "api_key", "sha256:abc")
    identity.elevate_trust(agent.agent_id, TrustLevel.VERIFIED)

    accountant = ResourceAccountant()
    accountant.set_quota("agent-1", ResourceKind.API_CALLS, limit=100.0)

    policy = PolicyDSLEngine()
    policy.add_rule(
        name="block-dangerous",
        effect=RuleEffect.DENY,
        scope=PolicyScope.ACTION,
        conditions=[{"field": "action", "op": ConditionOp.EQUALS, "value": "rm_rf"}],
    )

    versioner = BehaviorVersioner()
    versioner.capture_signature("agent-1", action_profile={"read": 10}, success_rate=0.95)
    versioner.create_baseline("agent-1", is_golden=True)

    config = PipelineConfig(
        stages=[
            PipelineStage.IDENTITY,
            PipelineStage.RESOURCE_CHECK,
            PipelineStage.POLICY,
            PipelineStage.BEHAVIOR_CHECK,
        ],
        mode=PipelineMode.STRICT,
    )
    pipeline = SafetyPipeline(config)
    pipeline.register_stage(PipelineStage.IDENTITY, make_identity_stage(identity))
    pipeline.register_stage(PipelineStage.RESOURCE_CHECK, make_resource_stage(accountant))
    pipeline.register_stage(PipelineStage.POLICY, make_policy_stage(policy))
    pipeline.register_stage(PipelineStage.BEHAVIOR_CHECK, make_behavior_stage(versioner))

    return pipeline, identity, accountant, versioner


@pytest.mark.asyncio
async def test_authorized_agent_passes(full_pipeline):
    pipeline, *_ = full_pipeline
    result = await pipeline.evaluate("agent-1", {
        "agent_id": "agent-1", "action": "read_file",
    })
    assert result.final_verdict == StageVerdict.PASS


@pytest.mark.asyncio
async def test_unknown_agent_blocked(full_pipeline):
    pipeline, *_ = full_pipeline
    result = await pipeline.evaluate("hacker", {
        "agent_id": "hacker", "action": "read_file",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert result.failed_at == PipelineStage.IDENTITY


@pytest.mark.asyncio
async def test_dangerous_action_blocked(full_pipeline):
    pipeline, *_ = full_pipeline
    result = await pipeline.evaluate("agent-1", {
        "agent_id": "agent-1", "action": "rm_rf",
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert result.failed_at == PipelineStage.POLICY


@pytest.mark.asyncio
async def test_resource_exhaustion_blocks(full_pipeline):
    pipeline, _, accountant, _ = full_pipeline
    accountant.allocate("agent-1", ResourceKind.API_CALLS, 100.0)
    result = await pipeline.evaluate("agent-1", {
        "agent_id": "agent-1", "action": "read_file",
        "resource_kind": ResourceKind.API_CALLS, "resource_amount": 1.0,
    })
    assert result.final_verdict == StageVerdict.FAIL
    assert result.failed_at == PipelineStage.RESOURCE_CHECK


@pytest.mark.asyncio
async def test_behavior_drift_warns(full_pipeline):
    pipeline, _, _, versioner = full_pipeline
    versioner.capture_signature("agent-1", action_profile={"read": 10, "new_action": 5},
                                success_rate=0.90)
    config = PipelineConfig(
        stages=[PipelineStage.BEHAVIOR_CHECK],
        mode=PipelineMode.STRICT,
    )
    p = SafetyPipeline(config)
    p.register_stage(PipelineStage.BEHAVIOR_CHECK, make_behavior_stage(versioner))
    result = await p.evaluate("agent-1", {"agent_id": "agent-1"})
    assert result.final_verdict == StageVerdict.WARN


@pytest.mark.asyncio
async def test_behavior_diverged_blocks(full_pipeline):
    pipeline, _, _, versioner = full_pipeline
    versioner.capture_signature("agent-1", action_profile={"z": 10}, success_rate=0.4)
    config = PipelineConfig(
        stages=[PipelineStage.BEHAVIOR_CHECK],
        mode=PipelineMode.STRICT,
    )
    p = SafetyPipeline(config)
    p.register_stage(PipelineStage.BEHAVIOR_CHECK, make_behavior_stage(versioner))
    result = await p.evaluate("agent-1", {"agent_id": "agent-1"})
    assert result.final_verdict == StageVerdict.FAIL
