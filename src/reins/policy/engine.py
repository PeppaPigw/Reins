from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import ulid

from reins.kernel.types import GrantRef, RiskTier
from reins.policy.audit import PolicyAuditRecord, PolicyAuditSink
from reins.policy.capabilities import CAPABILITY_RISK_TIERS
from reins.policy.approval.ledger import EffectDescriptor
from reins.policy.constraints import ConstraintRegistry, RuntimeConstraint
from reins.policy.rules import PolicyRule, PolicyRuleSet, PolicyExpressionError


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    risk_tier: RiskTier
    grant_id: str | None
    reason: str
    matched_rule: str | None = None
    triggered_constraints: tuple[str, ...] = ()


class PolicyEngine:
    """Evaluates capability requests against policy bundles.

    Default behavior is unchanged when rules, constraints, and audit sinks are
    not configured:
    - T0/T1 capabilities are auto-allowed
    - T2/T3 capabilities require approval
    - T4 capabilities are denied
    - remote A2A calls are routed to the remote boundary
    """

    def __init__(
        self,
        *,
        rules: PolicyRuleSet | Sequence[PolicyRule | Mapping[str, Any]] | None = None,
        constraints: (
            ConstraintRegistry | Sequence[RuntimeConstraint | Mapping[str, Any]] | None
        ) = None,
        audit_sink: PolicyAuditSink | None = None,
    ) -> None:
        self._rules = rules if isinstance(rules, PolicyRuleSet) else PolicyRuleSet.from_data(rules)
        self._constraints = (
            constraints
            if isinstance(constraints, ConstraintRegistry)
            else ConstraintRegistry.from_data(constraints)
        )
        self._audit_sink = audit_sink

    @property
    def rules(self) -> PolicyRuleSet:
        return self._rules

    @property
    def constraints(self) -> ConstraintRegistry:
        return self._constraints

    @property
    def audit_sink(self) -> PolicyAuditSink | None:
        return self._audit_sink

    async def evaluate(
        self,
        capability: str,
        run_id: str,
        requested_by: str,
        effect_descriptor: EffectDescriptor | None = None,
        active_grants: list[GrantRef] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> PolicyDecision:
        tier_value = CAPABILITY_RISK_TIERS.get(capability)
        if tier_value is None:
            decision = PolicyDecision(
                "deny", RiskTier.T4, None, f"unknown capability: {capability}"
            )
            await self._record_audit(
                run_id=run_id,
                capability=capability,
                requested_by=requested_by,
                effect_descriptor=effect_descriptor,
                base_decision=None,
                final_decision=decision,
            )
            return decision
        risk_tier = RiskTier(tier_value)
        if capability == "a2a.agent.call" or capability.startswith("a2a.agent.call."):
            decision = PolicyDecision("route_remote", risk_tier, None, "remote boundary required")
            await self._record_audit(
                run_id=run_id,
                capability=capability,
                requested_by=requested_by,
                effect_descriptor=effect_descriptor,
                base_decision=decision,
                final_decision=decision,
            )
            return decision
        matched_grant = self._match_grant(capability, effect_descriptor, active_grants or [])
        base_decision = self._default_decision(
            capability=capability,
            run_id=run_id,
            requested_by=requested_by,
            effect_descriptor=effect_descriptor,
            risk_tier=risk_tier,
            matched_grant=matched_grant,
        )
        final_decision = base_decision
        eval_context = self._build_context(
            capability=capability,
            run_id=run_id,
            requested_by=requested_by,
            effect_descriptor=effect_descriptor,
            risk_tier=risk_tier,
            base_decision=base_decision,
            matched_grant=matched_grant,
            extra_context=context,
        )

        if self._rules and base_decision.decision != "route_remote":
            try:
                match = self._rules.evaluate(eval_context)
            except PolicyExpressionError as exc:
                final_decision = PolicyDecision(
                    "deny",
                    risk_tier,
                    None,
                    f"policy rule evaluation failed: {exc}",
                )
            else:
                if match is not None:
                    grant_id = base_decision.grant_id
                    if match.decision != "allow":
                        grant_id = None
                    elif matched_grant is None and grant_id is None:
                        grant_id = self._issue_grant_id(run_id, requested_by, capability)
                    final_decision = PolicyDecision(
                        decision=match.decision,
                        risk_tier=risk_tier,
                        grant_id=grant_id,
                        reason=match.reason,
                        matched_rule=match.rule.name,
                    )
                    eval_context["policy"]["decision"] = final_decision.decision
                    eval_context["policy"]["matched_rule"] = match.rule.name

        if self._constraints:
            try:
                outcome = self._constraints.evaluate(eval_context, final_decision.decision)
            except PolicyExpressionError as exc:
                final_decision = PolicyDecision(
                    "deny",
                    risk_tier,
                    None,
                    f"policy constraint evaluation failed: {exc}",
                    matched_rule=final_decision.matched_rule,
                )
            else:
                if outcome is not None:
                    final_decision = PolicyDecision(
                        decision=outcome.decision,
                        risk_tier=risk_tier,
                        grant_id=None,
                        reason=outcome.reason,
                        matched_rule=final_decision.matched_rule,
                        triggered_constraints=(outcome.constraint.name,),
                    )

        await self._record_audit(
            run_id=run_id,
            capability=capability,
            requested_by=requested_by,
            effect_descriptor=effect_descriptor,
            base_decision=base_decision,
            final_decision=final_decision,
            matched_grant=matched_grant,
        )
        return final_decision

    def _default_decision(
        self,
        *,
        capability: str,
        run_id: str,
        requested_by: str,
        effect_descriptor: EffectDescriptor | None,
        risk_tier: RiskTier,
        matched_grant: GrantRef | None,
    ) -> PolicyDecision:
        if matched_grant is not None:
            return PolicyDecision("allow", risk_tier, None, "matched active grant")
        if risk_tier <= RiskTier.T1:
            grant = self._issue_grant_id(run_id, requested_by, capability)
            return PolicyDecision("allow", risk_tier, grant, "low-risk capability")
        if risk_tier <= RiskTier.T3:
            reason = effect_descriptor.summary if effect_descriptor else "approval required"
            return PolicyDecision("ask", risk_tier, None, reason)
        return PolicyDecision("deny", risk_tier, None, "risk tier exceeds local policy")

    @staticmethod
    def _issue_grant_id(run_id: str, requested_by: str, capability: str) -> str:
        return f"{run_id}:{requested_by}:{capability}:{ulid.new()}"

    @staticmethod
    def _build_context(
        *,
        capability: str,
        run_id: str,
        requested_by: str,
        effect_descriptor: EffectDescriptor | None,
        risk_tier: RiskTier,
        base_decision: PolicyDecision,
        matched_grant: GrantRef | None,
        extra_context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        resource = effect_descriptor.resource if effect_descriptor is not None else None
        context: dict[str, Any] = {
            "command": {
                "capability": capability,
                "kind": capability,
                "risk_tier": int(risk_tier),
                "resource": resource,
            },
            "effect": {
                "capability": effect_descriptor.capability
                if effect_descriptor is not None
                else capability,
                "resource": resource,
                "summary": effect_descriptor.summary if effect_descriptor else None,
                "descriptor_hash": (
                    effect_descriptor.descriptor_hash if effect_descriptor else None
                ),
                "reversibility": (effect_descriptor.reversibility if effect_descriptor else None),
                "rollback_strategy": (
                    effect_descriptor.rollback_strategy if effect_descriptor else None
                ),
            },
            "request": {
                "run_id": run_id,
                "requested_by": requested_by,
            },
            "adapter": {
                "type": capability.split(".", 1)[0],
            },
            "policy": {
                "default_decision": base_decision.decision,
                "decision": base_decision.decision,
                "matched_grant": matched_grant is not None,
            },
        }
        if extra_context:
            for key, value in extra_context.items():
                context[key] = value
        return context

    @staticmethod
    def _match_grant(
        capability: str,
        effect_descriptor: EffectDescriptor | None,
        active_grants: list[GrantRef],
    ) -> GrantRef | None:
        if effect_descriptor is None:
            return None
        now = time.time()
        for grant in active_grants:
            if grant.capability != capability:
                continue
            if grant.scope != effect_descriptor.resource:
                continue
            if grant.approval_hash not in (None, effect_descriptor.descriptor_hash):
                continue
            # Check if grant has expired
            if grant.issued_at + grant.ttl_seconds < now:
                continue
            return grant
        return None

    async def _record_audit(
        self,
        *,
        run_id: str,
        capability: str,
        requested_by: str,
        effect_descriptor: EffectDescriptor | None,
        base_decision: PolicyDecision | None,
        final_decision: PolicyDecision,
        matched_grant: GrantRef | None = None,
    ) -> None:
        if self._audit_sink is None:
            return
        record = PolicyAuditRecord.create(
            run_id=run_id,
            capability=capability,
            requested_by=requested_by,
            risk_tier=int(final_decision.risk_tier),
            decision=final_decision.decision,
            reason=final_decision.reason,
            resource=effect_descriptor.resource if effect_descriptor else None,
            descriptor_hash=(
                effect_descriptor.descriptor_hash if effect_descriptor is not None else None
            ),
            grant_id=final_decision.grant_id,
            base_decision=base_decision.decision if base_decision is not None else None,
            matched_rule=final_decision.matched_rule,
            triggered_constraints=final_decision.triggered_constraints,
            metadata={
                "matched_grant_id": matched_grant.grant_id if matched_grant else None,
            },
        )
        await self._audit_sink.record(record)
