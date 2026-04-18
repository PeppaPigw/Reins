from __future__ import annotations

import time
from dataclasses import dataclass

import ulid

from reins.kernel.types import GrantRef, RiskTier
from reins.policy.capabilities import CAPABILITY_RISK_TIERS
from reins.policy.approval.ledger import EffectDescriptor


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    risk_tier: RiskTier
    grant_id: str | None
    reason: str


class PolicyEngine:
    """Evaluates capability requests against policy bundles."""

    async def evaluate(
        self,
        capability: str,
        run_id: str,
        requested_by: str,
        effect_descriptor: EffectDescriptor | None = None,
        active_grants: list[GrantRef] | None = None,
    ) -> PolicyDecision:
        tier_value = CAPABILITY_RISK_TIERS.get(capability)
        if tier_value is None:
            return PolicyDecision(
                "deny", RiskTier.T4, None, f"unknown capability: {capability}"
            )
        risk_tier = RiskTier(tier_value)
        if capability == "a2a.agent.call" or capability.startswith("a2a.agent.call."):
            return PolicyDecision(
                "route_remote", risk_tier, None, "remote boundary required"
            )
        matched_grant = self._match_grant(
            capability, effect_descriptor, active_grants or []
        )
        if matched_grant is not None:
            return PolicyDecision("allow", risk_tier, None, "matched active grant")
        if risk_tier <= RiskTier.T1:
            grant = f"{run_id}:{requested_by}:{capability}:{ulid.new()}"
            return PolicyDecision("allow", risk_tier, grant, "low-risk capability")
        if risk_tier <= RiskTier.T3:
            reason = (
                effect_descriptor.summary if effect_descriptor else "approval required"
            )
            return PolicyDecision("ask", risk_tier, None, reason)
        return PolicyDecision("deny", risk_tier, None, "risk tier exceeds local policy")

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
