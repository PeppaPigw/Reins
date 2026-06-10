"""Integration: wires concrete safety modules into the SafetyPipeline as stage handlers."""

from __future__ import annotations

from typing import Any

from reins.safety_pipeline.types import PipelineStage, StageVerdict


def make_identity_stage(identity_provider: Any) -> Any:
    """Creates a pipeline stage handler from an IdentityProvider."""
    from reins.identity import TrustLevel

    def handler(ctx: dict[str, Any]) -> StageVerdict:
        agent_id = ctx.get("agent_id", "")
        ident = identity_provider.get_identity(agent_id)
        if not ident:
            return StageVerdict.FAIL
        if ident.trust_level == TrustLevel.UNTRUSTED:
            return StageVerdict.FAIL
        return StageVerdict.PASS

    return handler


def make_resource_stage(accountant: Any) -> Any:
    """Creates a pipeline stage handler from a ResourceAccountant."""
    from reins.resource_accounting import AllocationResult, ResourceKind

    def handler(ctx: dict[str, Any]) -> StageVerdict:
        agent_id = ctx.get("agent_id", "")
        resource = ctx.get("resource_kind", ResourceKind.API_CALLS)
        amount = ctx.get("resource_amount", 1.0)
        req = accountant.allocate(agent_id, resource, amount)
        if req.result == AllocationResult.DENIED:
            return StageVerdict.FAIL
        if req.result == AllocationResult.THROTTLED:
            return StageVerdict.WARN
        return StageVerdict.PASS

    return handler


def make_policy_stage(policy_engine: Any) -> Any:
    """Creates a pipeline stage handler from a PolicyDSLEngine."""
    from reins.policy_dsl import RuleEffect

    def handler(ctx: dict[str, Any]) -> StageVerdict:
        evaluation = policy_engine.evaluate(ctx)
        if not evaluation or not evaluation.matched:
            return StageVerdict.PASS
        if evaluation.effect == RuleEffect.DENY:
            return StageVerdict.FAIL
        if evaluation.effect in (RuleEffect.ESCALATE, RuleEffect.THROTTLE):
            return StageVerdict.WARN
        return StageVerdict.PASS

    return handler


def make_behavior_stage(versioner: Any) -> Any:
    """Creates a pipeline stage handler from a BehaviorVersioner."""
    from reins.behavior_versioning import DriftStatus

    def handler(ctx: dict[str, Any]) -> StageVerdict:
        agent_id = ctx.get("agent_id", "")
        drift = versioner.detect_drift(agent_id)
        if drift == DriftStatus.DIVERGED:
            return StageVerdict.FAIL
        if drift == DriftStatus.DRIFTING:
            return StageVerdict.WARN
        return StageVerdict.PASS

    return handler


def make_temporal_stage(checker: Any) -> Any:
    """Creates a pipeline stage handler from a TemporalChecker."""
    from reins.temporal_logic import PropertyStatus

    def handler(ctx: dict[str, Any]) -> StageVerdict:
        results = checker.check_all(ctx.get("trace", []))
        if not results:
            return StageVerdict.SKIP
        if any(r.status == PropertyStatus.VIOLATED for r in results):
            return StageVerdict.FAIL
        return StageVerdict.PASS

    return handler
