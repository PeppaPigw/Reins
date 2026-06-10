from __future__ import annotations

from collections import defaultdict

from reins.explanation.types import (
    AudienceLevel,
    Counterfactual,
    DecisionFactor,
    DecisionRecord,
    Explanation,
    ExplanationDepth,
    ExplanationStats,
    FactorKind,
)


class ExplanationEngine:
    """Generates human-readable explanations of agent decisions with causal attribution.

    Records decisions with their contributing factors, generates explanations
    at varying depths for different audiences, and supports counterfactual reasoning.
    """

    def __init__(self) -> None:
        self._decisions: dict[str, DecisionRecord] = {}
        self._explanations: list[Explanation] = []

    def record_decision(self, agent_id: str, action: str, outcome: str = "",
                        context: dict | None = None,
                        factors: list[DecisionFactor] | None = None,
                        alternatives: list[str] | None = None) -> DecisionRecord:
        record = DecisionRecord(
            agent_id=agent_id,
            action=action,
            outcome=outcome,
            context=context or {},
            factors=tuple(factors or []),
            alternatives_considered=tuple(alternatives or []),
        )
        self._decisions[record.decision_id] = record
        return record

    def explain(self, decision_id: str, depth: ExplanationDepth = ExplanationDepth.STANDARD,
                audience: AudienceLevel = AudienceLevel.DEVELOPER) -> Explanation | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        summary = self._generate_summary(decision, depth, audience)
        counterfactuals = self._generate_counterfactuals(decision)
        confidence = self._compute_confidence(decision)

        explanation = Explanation(
            decision_id=decision_id,
            agent_id=decision.agent_id,
            summary=summary,
            factors=decision.factors,
            counterfactuals=tuple(counterfactuals),
            depth=depth,
            audience=audience,
            confidence=confidence,
        )
        self._explanations.append(explanation)
        return explanation

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        return self._decisions.get(decision_id)

    def get_decisions(self, agent_id: str | None = None) -> list[DecisionRecord]:
        decisions = list(self._decisions.values())
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        return decisions

    def get_explanations(self, decision_id: str | None = None,
                         audience: AudienceLevel | None = None) -> list[Explanation]:
        explanations = self._explanations
        if decision_id:
            explanations = [e for e in explanations if e.decision_id == decision_id]
        if audience:
            explanations = [e for e in explanations if e.audience == audience]
        return explanations

    def add_counterfactual(self, decision_id: str, condition: str,
                           alternative_outcome: str, likelihood: float = 0.5,
                           impact: str = "") -> Counterfactual | None:
        if decision_id not in self._decisions:
            return None
        return Counterfactual(
            condition=condition,
            alternative_outcome=alternative_outcome,
            likelihood=likelihood,
            impact=impact,
        )

    def get_stats(self) -> ExplanationStats:
        total_decisions = len(self._decisions)
        total_explanations = len(self._explanations)

        factor_counts = [len(d.factors) for d in self._decisions.values()]
        avg_factors = sum(factor_counts) / len(factor_counts) if factor_counts else 0.0

        confidences = [e.confidence for e in self._explanations]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        by_depth: dict[str, int] = defaultdict(int)
        by_audience: dict[str, int] = defaultdict(int)
        for e in self._explanations:
            by_depth[e.depth.value] += 1
            by_audience[e.audience.value] += 1

        return ExplanationStats(
            total_decisions=total_decisions,
            total_explanations=total_explanations,
            avg_factors_per_decision=avg_factors,
            avg_confidence=avg_confidence,
            by_depth=dict(by_depth),
            by_audience=dict(by_audience),
        )

    def _generate_summary(self, decision: DecisionRecord,
                          depth: ExplanationDepth,
                          audience: AudienceLevel) -> str:
        action_desc = decision.action

        if depth == ExplanationDepth.BRIEF:
            return f"Chose to {action_desc}"

        causal = [f for f in decision.factors if f.kind == FactorKind.CAUSAL]
        supporting = [f for f in decision.factors if f.kind == FactorKind.SUPPORTING]
        inhibiting = [f for f in decision.factors if f.kind == FactorKind.INHIBITING]

        parts = [f"Decided to {action_desc}"]

        if causal:
            causes = ", ".join(f.description for f in causal[:3])
            parts.append(f"because {causes}")

        if depth in (ExplanationDepth.DETAILED, ExplanationDepth.TECHNICAL):
            if supporting:
                supports = ", ".join(f.description for f in supporting[:2])
                parts.append(f"supported by {supports}")
            if inhibiting:
                inhibits = ", ".join(f.description for f in inhibiting[:2])
                parts.append(f"despite {inhibits}")

        if decision.alternatives_considered and depth == ExplanationDepth.TECHNICAL:
            alts = ", ".join(decision.alternatives_considered[:3])
            parts.append(f"(alternatives considered: {alts})")

        if audience == AudienceLevel.END_USER:
            return parts[0]
        return ". ".join(parts)

    def _generate_counterfactuals(self, decision: DecisionRecord) -> list[Counterfactual]:
        counterfactuals = []
        for alt in decision.alternatives_considered:
            counterfactuals.append(Counterfactual(
                condition=f"If '{alt}' had been chosen instead",
                alternative_outcome=f"Would have taken path: {alt}",
                likelihood=0.5,
            ))

        for factor in decision.factors:
            if factor.kind == FactorKind.CAUSAL and factor.confidence < 0.9:
                counterfactuals.append(Counterfactual(
                    condition=f"If '{factor.description}' were not present",
                    alternative_outcome="Decision might have differed",
                    likelihood=1.0 - factor.confidence,
                ))

        return counterfactuals[:5]

    def _compute_confidence(self, decision: DecisionRecord) -> float:
        if not decision.factors:
            return 0.3

        weights = [f.weight * f.confidence for f in decision.factors]
        total_weight = sum(f.weight for f in decision.factors)
        if total_weight == 0:
            return 0.3

        weighted_confidence = sum(weights) / total_weight

        causal_count = sum(1 for f in decision.factors if f.kind == FactorKind.CAUSAL)
        factor_bonus = min(0.2, causal_count * 0.05)

        return min(1.0, weighted_confidence + factor_bonus)
