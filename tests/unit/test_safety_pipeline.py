"""Tests for async safety orchestration pipeline."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from reins.safety_pipeline import (
    PipelineConfig,
    PipelineEvent,
    PipelineExecution,
    PipelineMode,
    PipelineStage,
    SafetyPipeline,
    StageResult,
    StageVerdict,
)


@pytest.fixture
def pipeline() -> SafetyPipeline:
    return SafetyPipeline()


@pytest.fixture
def strict_pipeline() -> SafetyPipeline:
    return SafetyPipeline(PipelineConfig(mode=PipelineMode.STRICT))


@pytest.fixture
def permissive_pipeline() -> SafetyPipeline:
    return SafetyPipeline(PipelineConfig(mode=PipelineMode.PERMISSIVE))


@pytest.fixture
def dry_run_pipeline() -> SafetyPipeline:
    return SafetyPipeline(PipelineConfig(mode=PipelineMode.DRY_RUN))


@pytest.mark.asyncio
async def test_empty_pipeline_passes(pipeline):
    result = await pipeline.evaluate("agent-1", {})
    assert result.final_verdict == StageVerdict.PASS
    assert result.agent_id == "agent-1"


@pytest.mark.asyncio
async def test_all_pass(pipeline):
    def identity_check(ctx):
        return StageVerdict.PASS

    def policy_check(ctx):
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, identity_check)
    pipeline.register_stage(PipelineStage.POLICY, policy_check)
    result = await pipeline.evaluate("a", {"authenticated": True})
    assert result.final_verdict == StageVerdict.PASS


@pytest.mark.asyncio
async def test_strict_short_circuits_on_fail(strict_pipeline):
    calls = []

    def fail_stage(ctx):
        calls.append("identity")
        return StageVerdict.FAIL

    def second_stage(ctx):
        calls.append("policy")
        return StageVerdict.PASS

    strict_pipeline.register_stage(PipelineStage.IDENTITY, fail_stage)
    strict_pipeline.register_stage(PipelineStage.POLICY, second_stage)
    result = await strict_pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.FAIL
    assert result.failed_at == PipelineStage.IDENTITY
    assert "policy" not in calls


@pytest.mark.asyncio
async def test_permissive_runs_all_stages(permissive_pipeline):
    calls = []

    def fail_stage(ctx):
        calls.append("identity")
        return StageVerdict.FAIL

    def pass_stage(ctx):
        calls.append("policy")
        return StageVerdict.PASS

    permissive_pipeline.register_stage(PipelineStage.IDENTITY, fail_stage)
    permissive_pipeline.register_stage(PipelineStage.POLICY, pass_stage)
    result = await permissive_pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.FAIL
    assert "identity" in calls
    assert "policy" in calls


@pytest.mark.asyncio
async def test_dry_run_downgrades_fail_to_warn(dry_run_pipeline):
    def fail_stage(ctx):
        return StageVerdict.FAIL

    dry_run_pipeline.register_stage(PipelineStage.IDENTITY, fail_stage)
    result = await dry_run_pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.WARN
    assert result.stages[0].verdict == StageVerdict.WARN


@pytest.mark.asyncio
async def test_async_handler(pipeline):
    async def async_check(ctx):
        await asyncio.sleep(0.001)
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, async_check)
    result = await pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.PASS


@pytest.mark.asyncio
async def test_timeout_handling():
    config = PipelineConfig(timeout_ms=50, mode=PipelineMode.STRICT)
    pipeline = SafetyPipeline(config)

    async def slow_handler(ctx):
        await asyncio.sleep(1.0)
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, slow_handler)
    result = await pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.FAIL
    assert result.failed_at == PipelineStage.IDENTITY


@pytest.mark.asyncio
async def test_exception_in_handler(strict_pipeline):
    def bad_handler(ctx):
        raise RuntimeError("boom")

    strict_pipeline.register_stage(PipelineStage.POLICY, bad_handler)
    result = await strict_pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.FAIL


@pytest.mark.asyncio
async def test_warn_verdict(pipeline):
    def warn_handler(ctx):
        return StageVerdict.WARN

    pipeline.register_stage(PipelineStage.BEHAVIOR_CHECK, warn_handler)
    result = await pipeline.evaluate("a", {})
    assert result.final_verdict == StageVerdict.WARN


@pytest.mark.asyncio
async def test_skip_unregistered_stages(pipeline):
    result = await pipeline.evaluate("a", {})
    for stage_result in result.stages:
        assert stage_result.verdict == StageVerdict.SKIP


@pytest.mark.asyncio
async def test_event_emission(pipeline):
    received: list[PipelineEvent] = []
    pipeline.add_listener(lambda e: received.append(e))

    def pass_handler(ctx):
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, pass_handler)
    await pipeline.evaluate("agent-x", {})
    assert any(e.event_type == "pipeline.started" for e in received)
    assert any(e.event_type == "pipeline.completed" for e in received)
    assert any(e.event_type == "stage.completed" for e in received)


@pytest.mark.asyncio
async def test_event_emission_disabled():
    config = PipelineConfig(emit_events=False)
    pipeline = SafetyPipeline(config)
    received: list[PipelineEvent] = []
    pipeline.add_listener(lambda e: received.append(e))

    def pass_handler(ctx):
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, pass_handler)
    await pipeline.evaluate("a", {})
    assert len(received) == 0


@pytest.mark.asyncio
async def test_evaluate_batch(pipeline):
    def check(ctx):
        return StageVerdict.PASS if ctx.get("ok") else StageVerdict.FAIL

    pipeline.register_stage(PipelineStage.IDENTITY, check)
    results = await pipeline.evaluate_batch([
        ("a", {"ok": True}),
        ("b", {"ok": False}),
    ])
    assert results[0].final_verdict == StageVerdict.PASS
    assert results[1].final_verdict == StageVerdict.FAIL


@pytest.mark.asyncio
async def test_get_executions(pipeline):
    def pass_handler(ctx):
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, pass_handler)
    await pipeline.evaluate("a", {})
    await pipeline.evaluate("b", {})
    assert len(pipeline.get_executions()) == 2
    assert len(pipeline.get_executions(agent_id="a")) == 1


@pytest.mark.asyncio
async def test_get_stats(pipeline):
    def check(ctx):
        return StageVerdict.PASS if ctx.get("ok") else StageVerdict.FAIL

    pipeline.register_stage(PipelineStage.IDENTITY, check)
    await pipeline.evaluate("a", {"ok": True})
    await pipeline.evaluate("b", {"ok": False})
    stats = pipeline.get_stats()
    assert stats.total_executions == 2
    assert stats.passed == 1
    assert stats.failed == 1


@pytest.mark.asyncio
async def test_remove_stage(pipeline):
    def handler(ctx):
        return StageVerdict.FAIL

    pipeline.register_stage(PipelineStage.IDENTITY, handler)
    assert pipeline.remove_stage(PipelineStage.IDENTITY) is True
    assert pipeline.remove_stage(PipelineStage.IDENTITY) is False


@pytest.mark.asyncio
async def test_custom_stage_order():
    config = PipelineConfig(stages=[PipelineStage.POLICY, PipelineStage.IDENTITY])
    pipeline = SafetyPipeline(config)
    order = []

    def policy_h(ctx):
        order.append("policy")
        return StageVerdict.PASS

    def identity_h(ctx):
        order.append("identity")
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.POLICY, policy_h)
    pipeline.register_stage(PipelineStage.IDENTITY, identity_h)
    await pipeline.evaluate("a", {})
    assert order == ["policy", "identity"]


@pytest.mark.asyncio
async def test_context_passed_to_handlers(pipeline):
    received_ctx = {}

    def handler(ctx):
        received_ctx.update(ctx)
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, handler)
    await pipeline.evaluate("a", {"user": "admin", "action": "deploy"})
    assert received_ctx == {"user": "admin", "action": "deploy"}


@pytest.mark.asyncio
async def test_full_pipeline_integration():
    config = PipelineConfig(
        stages=[
            PipelineStage.IDENTITY,
            PipelineStage.RESOURCE_CHECK,
            PipelineStage.POLICY,
            PipelineStage.INVARIANTS,
            PipelineStage.BEHAVIOR_CHECK,
            PipelineStage.TEMPORAL_CHECK,
            PipelineStage.COMPOSABILITY,
            PipelineStage.AUDIT,
        ],
        mode=PipelineMode.STRICT,
    )
    pipeline = SafetyPipeline(config)

    def identity(ctx):
        return StageVerdict.PASS if ctx.get("authenticated") else StageVerdict.FAIL

    def resource(ctx):
        return StageVerdict.PASS if ctx.get("quota_ok") else StageVerdict.FAIL

    def policy(ctx):
        return StageVerdict.PASS if ctx.get("policy_allows") else StageVerdict.FAIL

    def invariants(ctx):
        return StageVerdict.PASS

    def behavior(ctx):
        return StageVerdict.WARN if ctx.get("drifting") else StageVerdict.PASS

    def temporal(ctx):
        return StageVerdict.PASS

    def composability(ctx):
        return StageVerdict.PASS

    def audit(ctx):
        return StageVerdict.PASS

    pipeline.register_stage(PipelineStage.IDENTITY, identity)
    pipeline.register_stage(PipelineStage.RESOURCE_CHECK, resource)
    pipeline.register_stage(PipelineStage.POLICY, policy)
    pipeline.register_stage(PipelineStage.INVARIANTS, invariants)
    pipeline.register_stage(PipelineStage.BEHAVIOR_CHECK, behavior)
    pipeline.register_stage(PipelineStage.TEMPORAL_CHECK, temporal)
    pipeline.register_stage(PipelineStage.COMPOSABILITY, composability)
    pipeline.register_stage(PipelineStage.AUDIT, audit)

    good = await pipeline.evaluate("trusted-agent", {
        "authenticated": True, "quota_ok": True,
        "policy_allows": True, "drifting": False,
    })
    assert good.final_verdict == StageVerdict.PASS

    bad = await pipeline.evaluate("hacker", {
        "authenticated": False, "quota_ok": True,
        "policy_allows": True,
    })
    assert bad.final_verdict == StageVerdict.FAIL
    assert bad.failed_at == PipelineStage.IDENTITY

    drift = await pipeline.evaluate("drifty", {
        "authenticated": True, "quota_ok": True,
        "policy_allows": True, "drifting": True,
    })
    assert drift.final_verdict == StageVerdict.WARN
