from __future__ import annotations

from collections import defaultdict

from reins.interpretability.types import (
    Audience,
    ContrastiveExplanation,
    DecisionRecord,
    Explanation,
    ExplanationKind,
    Factor,
    Fidelity,
    InterpretabilityStats,
)


class InterpretabilityEngine:
    """Makes agent decisions transparent and explainable.

    Generates explanations at multiple levels of abstraction for different
    audiences. Supports feature attribution, contrastive explanations,
    and chain-of-thought reconstruction.
    """

    def __init__(self, min_contribution: float = 0.05) -> None:
        self._min_contribution = min_contribution
        self._decisions: dict[str, DecisionRecord] = {}
        self._explanations: list[Explanation] = []

    def record_decision(self, agent_id: str, action: str,
                        inputs: dict | None = None,
                        context: dict | None = None,
                        outcome: str = "",
                        outcome_value: float = 0.0) -> DecisionRecord:
        record = DecisionRecord(
            agent_id=agent_id, action=action,
            inputs=inputs or {}, context=context or {},
            outcome=outcome, outcome_value=outcome_value,
        )
        self._decisions[record.decision_id] = record
        return record

    def explain_by_attribution(self, decision_id: str,
                               factors: list[tuple[str, float, str]],
                               audience: Audience = Audience.DEVELOPER) -> Explanation | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        sorted_factors = sorted(factors, key=lambda f: -abs(f[1]))
        significant = [
            Factor(name=name, contribution=contrib,
                   direction="positive" if contrib >= 0 else "negative",
                   description=desc)
            for name, contrib, desc in sorted_factors
            if abs(contrib) >= self._min_contribution
        ]

        total = sum(abs(f.contribution) for f in significant)
        fidelity = self._assess_fidelity(total)

        top_factor = significant[0] if significant else None
        summary = (
            f"Chose '{decision.action}' primarily because of {top_factor.name} "
            f"(contribution: {top_factor.contribution:.2f})"
            if top_factor else f"Chose '{decision.action}' with no dominant factor"
        )

        explanation = Explanation(
            decision_id=decision_id,
            kind=ExplanationKind.FEATURE_ATTRIBUTION,
            audience=audience,
            summary=summary,
            factors=tuple(significant),
            fidelity=fidelity,
            confidence=min(1.0, total),
        )
        self._explanations.append(explanation)
        return explanation

    def explain_contrastive(self, decision_id: str,
                            rejected_action: str,
                            differentiating_factors: list[tuple[str, float, str]],
                            audience: Audience = Audience.DEVELOPER) -> Explanation | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        factors = [
            Factor(name=name, contribution=contrib,
                   direction="positive" if contrib >= 0 else "negative",
                   description=desc)
            for name, contrib, desc in differentiating_factors
        ]

        reason_parts = [f.name for f in factors[:3] if f.contribution > 0]
        reason = ", ".join(reason_parts) if reason_parts else "multiple factors"
        summary = f"Chose '{decision.action}' over '{rejected_action}' because of {reason}"

        explanation = Explanation(
            decision_id=decision_id,
            kind=ExplanationKind.CONTRASTIVE,
            audience=audience,
            summary=summary,
            factors=tuple(factors),
            fidelity=Fidelity.MEDIUM,
            confidence=0.7,
        )
        self._explanations.append(explanation)
        return explanation

    def explain_chain_of_thought(self, decision_id: str,
                                  steps: list[str],
                                  audience: Audience = Audience.DEVELOPER) -> Explanation | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        factors = [
            Factor(name=f"step_{i+1}", contribution=1.0 / len(steps),
                   description=step)
            for i, step in enumerate(steps)
        ]

        summary = f"Reasoning chain: {' -> '.join(steps[:3])}"
        if len(steps) > 3:
            summary += f" -> ... ({len(steps)} steps total)"

        explanation = Explanation(
            decision_id=decision_id,
            kind=ExplanationKind.CHAIN_OF_THOUGHT,
            audience=audience,
            summary=summary,
            factors=tuple(factors),
            fidelity=Fidelity.HIGH,
            confidence=0.9,
        )
        self._explanations.append(explanation)
        return explanation

    def get_explanations(self, decision_id: str | None = None,
                         kind: ExplanationKind | None = None,
                         audience: Audience | None = None) -> list[Explanation]:
        results = self._explanations
        if decision_id:
            results = [e for e in results if e.decision_id == decision_id]
        if kind:
            results = [e for e in results if e.kind == kind]
        if audience:
            results = [e for e in results if e.audience == audience]
        return results

    def simplify_for_audience(self, explanation: Explanation,
                              target: Audience) -> Explanation:
        if target == Audience.END_USER:
            factors = explanation.factors[:3]
            summary = explanation.summary.split(".")[0]
        elif target == Audience.OPERATOR:
            factors = explanation.factors[:5]
            summary = explanation.summary
        else:
            factors = explanation.factors
            summary = explanation.summary

        return Explanation(
            decision_id=explanation.decision_id,
            kind=explanation.kind,
            audience=target,
            summary=summary,
            factors=factors,
            fidelity=explanation.fidelity,
            confidence=explanation.confidence,
        )

    def get_stats(self) -> InterpretabilityStats:
        by_kind: dict[str, int] = defaultdict(int)
        by_audience: dict[str, int] = defaultdict(int)
        fidelity_scores = []

        for e in self._explanations:
            by_kind[e.kind.value] += 1
            by_audience[e.audience.value] += 1
            fidelity_scores.append(self._fidelity_to_score(e.fidelity))

        avg_fidelity = sum(fidelity_scores) / len(fidelity_scores) if fidelity_scores else 0.0
        explained_decisions = set(e.decision_id for e in self._explanations)
        coverage = len(explained_decisions) / len(self._decisions) if self._decisions else 0.0

        return InterpretabilityStats(
            total_decisions=len(self._decisions),
            total_explanations=len(self._explanations),
            by_kind=dict(by_kind),
            by_audience=dict(by_audience),
            avg_fidelity_score=avg_fidelity,
            coverage=coverage,
        )

    def _assess_fidelity(self, total_contribution: float) -> Fidelity:
        if total_contribution >= 0.8:
            return Fidelity.HIGH
        elif total_contribution >= 0.5:
            return Fidelity.MEDIUM
        elif total_contribution > 0:
            return Fidelity.LOW
        return Fidelity.UNKNOWN

    def _fidelity_to_score(self, fidelity: Fidelity) -> float:
        return {
            Fidelity.HIGH: 1.0,
            Fidelity.MEDIUM: 0.6,
            Fidelity.LOW: 0.3,
            Fidelity.UNKNOWN: 0.0,
        }.get(fidelity, 0.0)
