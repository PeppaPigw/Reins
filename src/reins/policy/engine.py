from __future__ import annotations

from dataclasses import dataclass

import ulid

from reins.kernel.types import RiskTier
from reins.policy.capabilities import CAPABILITY_RISK_TIERS


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
        effect_descriptor: dict | None = None,
    ) -> PolicyDecision:
        tier_value = CAPABILITY_RISK_TIERS.get(capability)
        if tier_value is None:
            return PolicyDecision("deny", RiskTier.T4, None, f"unknown capability: {capability}")
        risk_tier = RiskTier(tier_value)
        if capability.startswith("a2a.agent.call"):
            return PolicyDecision("route_remote", risk_tier, None, "remote boundary required")
        if risk_tier <= RiskTier.T1:
            grant = f"{run_id}:{requested_by}:{capability}:{ulid.new()}"
            return PolicyDecision("allow", risk_tier, grant, "low-risk capability")
        if risk_tier <= RiskTier.T3:
            reason = effect_descriptor.get("summary") if effect_descriptor else "approval required"
            return PolicyDecision("ask", risk_tier, None, reason)
        return PolicyDecision("deny", risk_tier, None, "risk tier exceeds local policy")
