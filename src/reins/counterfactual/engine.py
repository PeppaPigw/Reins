from __future__ import annotations

from collections import defaultdict

from reins.counterfactual.types import (
    CausalClaim,
    CausalStrength,
    CounterfactualResult,
    CounterfactualStats,
    Decision,
    Intervention,
    InterventionType,
    OutcomeComparison,
    WorldKind,
    WorldState,
)


class CounterfactualEngine:
    """Counterfactual reasoning engine for agent decision analysis.

    Enables "what-if" analysis by constructing counterfactual worlds where
    agents took different actions, then comparing outcomes to identify
    causal relationships and compute regret.
    """

    def __init__(self, regret_threshold: float = 0.1,
                 causal_confidence_min: float = 0.6) -> None:
        self._regret_threshold = regret_threshold
        self._causal_confidence_min = causal_confidence_min
        self._decisions: dict[str, Decision] = {}
        self._worlds: dict[str, WorldState] = {}
        self._interventions: list[Intervention] = []
        self._claims: list[CausalClaim] = []

    def record_decision(self, agent_id: str, action_taken: str,
                        alternatives: list[str] | None = None,
                        outcome_value: float = 0.0,
                        context: dict | None = None) -> Decision:
        decision = Decision(
            agent_id=agent_id, action_taken=action_taken,
            alternatives=tuple(alternatives or []),
            outcome_value=outcome_value,
            context=context or {},
        )
        self._decisions[decision.decision_id] = decision

        actual_world = WorldState(
            kind=WorldKind.ACTUAL,
            decisions=(decision.decision_id,),
            outcome_value=outcome_value,
        )
        self._worlds[actual_world.world_id] = actual_world
        return decision

    def intervene(self, decision_id: str, counterfactual_action: str,
                  simulated_outcome: float = 0.0,
                  intervention_type: InterventionType = InterventionType.ACTION_SWAP,
                  description: str = "") -> Intervention | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        intervention = Intervention(
            intervention_type=intervention_type,
            target_decision_id=decision_id,
            original_action=decision.action_taken,
            counterfactual_action=counterfactual_action,
            description=description or f"What if '{counterfactual_action}' instead of '{decision.action_taken}'?",
        )
        self._interventions.append(intervention)

        cf_world = WorldState(
            kind=WorldKind.COUNTERFACTUAL,
            decisions=(decision_id,),
            outcome_value=simulated_outcome,
            intervention=intervention,
        )
        self._worlds[cf_world.world_id] = cf_world
        return intervention

    def analyze_decision(self, decision_id: str) -> CounterfactualResult | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        actual_worlds = [
            w for w in self._worlds.values()
            if w.kind == WorldKind.ACTUAL and decision_id in w.decisions
        ]
        cf_worlds = [
            w for w in self._worlds.values()
            if w.kind == WorldKind.COUNTERFACTUAL and decision_id in w.decisions
        ]

        if not actual_worlds:
            return None

        actual = actual_worlds[0]
        best_cf = max(cf_worlds, key=lambda w: w.outcome_value) if cf_worlds else None

        if best_cf:
            regret = max(0.0, best_cf.outcome_value - actual.outcome_value)
            comparison = self._compare_outcomes(actual.outcome_value, best_cf.outcome_value)
        else:
            regret = 0.0
            comparison = OutcomeComparison.EQUIVALENT

        claims = self._derive_causal_claims(decision_id, actual, cf_worlds)

        return CounterfactualResult(
            actual_world=actual,
            counterfactual_worlds=tuple(cf_worlds),
            comparison=comparison,
            regret=regret,
            causal_claims=tuple(claims),
        )

    def compute_regret(self, decision_id: str) -> float:
        result = self.analyze_decision(decision_id)
        return result.regret if result else 0.0

    def get_high_regret_decisions(self, threshold: float | None = None) -> list[Decision]:
        t = threshold if threshold is not None else self._regret_threshold
        high_regret = []
        for did in self._decisions:
            if self.compute_regret(did) > t:
                high_regret.append(self._decisions[did])
        return high_regret

    def assess_causality(self, decision_id: str) -> CausalStrength:
        decision = self._decisions.get(decision_id)
        if not decision:
            return CausalStrength.IRRELEVANT

        cf_worlds = [
            w for w in self._worlds.values()
            if w.kind == WorldKind.COUNTERFACTUAL and decision_id in w.decisions
        ]
        actual_worlds = [
            w for w in self._worlds.values()
            if w.kind == WorldKind.ACTUAL and decision_id in w.decisions
        ]

        if not cf_worlds or not actual_worlds:
            return CausalStrength.IRRELEVANT

        actual_val = actual_worlds[0].outcome_value
        cf_outcomes = [w.outcome_value for w in cf_worlds]

        all_different = all(abs(v - actual_val) > self._regret_threshold for v in cf_outcomes)
        any_different = any(abs(v - actual_val) > self._regret_threshold for v in cf_outcomes)

        if all_different and all(v < actual_val for v in cf_outcomes):
            return CausalStrength.NECESSARY_AND_SUFFICIENT
        elif all_different:
            return CausalStrength.NECESSARY
        elif any_different:
            return CausalStrength.CONTRIBUTORY
        else:
            return CausalStrength.IRRELEVANT

    def get_causal_claims(self) -> list[CausalClaim]:
        return list(self._claims)

    def get_stats(self) -> CounterfactualStats:
        regrets = [self.compute_regret(did) for did in self._decisions]
        avg_regret = sum(regrets) / len(regrets) if regrets else 0.0

        by_strength: dict[str, int] = defaultdict(int)
        for claim in self._claims:
            by_strength[claim.strength.value] += 1

        return CounterfactualStats(
            total_decisions=len(self._decisions),
            total_interventions=len(self._interventions),
            total_worlds=len(self._worlds),
            avg_regret=avg_regret,
            causal_claims_found=len(self._claims),
            by_strength=dict(by_strength),
        )

    def _compare_outcomes(self, actual: float, counterfactual: float) -> OutcomeComparison:
        diff = counterfactual - actual
        if abs(diff) < self._regret_threshold:
            return OutcomeComparison.EQUIVALENT
        elif diff > 0:
            return OutcomeComparison.WORSE
        else:
            return OutcomeComparison.BETTER

    def _derive_causal_claims(self, decision_id: str, actual: WorldState,
                              cf_worlds: list[WorldState]) -> list[CausalClaim]:
        if not cf_worlds:
            return []

        claims = []
        actual_val = actual.outcome_value
        cf_outcomes = [w.outcome_value for w in cf_worlds]

        all_worse = all(v < actual_val - self._regret_threshold for v in cf_outcomes)
        all_better = all(v > actual_val + self._regret_threshold for v in cf_outcomes)
        any_different = any(abs(v - actual_val) > self._regret_threshold for v in cf_outcomes)

        if all_worse:
            strength = CausalStrength.NECESSARY_AND_SUFFICIENT
            confidence = min(1.0, len(cf_worlds) * 0.3)
        elif all_better:
            strength = CausalStrength.NECESSARY
            confidence = min(1.0, len(cf_worlds) * 0.25)
        elif any_different:
            strength = CausalStrength.CONTRIBUTORY
            confidence = min(1.0, len(cf_worlds) * 0.2)
        else:
            return []

        if confidence >= self._causal_confidence_min:
            claim = CausalClaim(
                cause_decision_id=decision_id,
                effect_description=f"Decision outcome value {actual_val:.2f}",
                strength=strength,
                confidence=confidence,
                evidence_worlds=tuple(w.world_id for w in cf_worlds),
            )
            claims.append(claim)
            self._claims.append(claim)

        return claims
