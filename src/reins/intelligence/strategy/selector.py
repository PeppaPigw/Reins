from __future__ import annotations

from typing import Any

from reins.intelligence.strategy.trust import TrustModel
from reins.intelligence.types import (
    StrategyRecommendation,
    TrustLevel,
    TrustScore,
)

RISK_TIER_LEVELS: dict[str, TrustLevel] = {
    "T1": TrustLevel.semi_auto,
    "T2": TrustLevel.auto,
    "T3": TrustLevel.full_autonomy,
    "T4": TrustLevel.full_autonomy,
}

ALWAYS_APPROVE_TIERS = frozenset({"T3", "T4"})


class StrategySelector:
    def __init__(self, trust_model: TrustModel, rules: list[dict[str, Any]] | None = None) -> None:
        self._trust = trust_model
        self._rules = rules or []

    async def recommend(self, task_context: dict[str, Any]) -> StrategyRecommendation:
        domain = task_context.get("domain", "general")
        risk_tier = task_context.get("risk_tier", "T1")
        trust = self._trust.get_domain_trust(domain)

        rule_override = self._check_rules(task_context)
        if rule_override:
            return rule_override

        requires_approval = self._needs_approval(trust, risk_tier, domain, task_context)
        strategy = self._select_strategy(trust.level, risk_tier)

        return StrategyRecommendation(
            strategy=strategy,
            trust_level=trust.level,
            requires_approval=requires_approval,
            rationale=self._build_rationale(trust, risk_tier, strategy),
            fallback_strategy="supervised_execution",
        )

    def get_domain_trust(self, domain: str) -> TrustScore:
        return self._trust.get_domain_trust(domain)

    async def record_outcome(self, domain: str, success: bool, severity: float = 0.0) -> None:
        await self._trust.record_outcome(domain, success, severity)

    def _needs_approval(
        self, trust: TrustScore, risk_tier: str, domain: str, context: dict[str, Any]
    ) -> bool:
        if risk_tier in ALWAYS_APPROVE_TIERS:
            return True
        if context.get("first_in_domain", False):
            return True
        if context.get("affects_production", False):
            return True
        if context.get("irreversible", False):
            return True

        required_level = RISK_TIER_LEVELS.get(risk_tier, TrustLevel.full_autonomy)
        level_order = list(TrustLevel)
        return level_order.index(trust.level) < level_order.index(required_level)

    def _select_strategy(self, trust_level: TrustLevel, risk_tier: str) -> str:
        if trust_level == TrustLevel.supervised:
            return "supervised_execution"
        if trust_level == TrustLevel.semi_auto:
            return "semi_autonomous" if risk_tier == "T1" else "supervised_execution"
        if trust_level == TrustLevel.auto:
            return "autonomous" if risk_tier in ("T1", "T2") else "semi_autonomous"
        return "full_autonomous"

    def _check_rules(self, context: dict[str, Any]) -> StrategyRecommendation | None:
        for rule in self._rules:
            condition = rule.get("condition", {})
            if all(context.get(k) == v for k, v in condition.items()):
                return StrategyRecommendation(
                    strategy=rule["strategy"],
                    trust_level=TrustLevel(rule.get("trust_level", "supervised")),
                    requires_approval=rule.get("requires_approval", True),
                    rationale=f"Rule override: {rule.get('name', 'unnamed')}",
                )
        return None

    def _build_rationale(self, trust: TrustScore, risk_tier: str, strategy: str) -> str:
        return (
            f"Domain '{trust.domain}' at {trust.level.value} "
            f"(score={trust.score:.2f}, successes={trust.effective_successes:.1f}). "
            f"Risk tier {risk_tier} → strategy '{strategy}'."
        )
