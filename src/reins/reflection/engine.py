from __future__ import annotations

from collections import defaultdict

from reins.reflection.types import (
    ConfidenceLevel,
    Decision,
    Insight,
    InsightCategory,
    Outcome,
    Reflection,
    ReflectionKind,
    ReflectionStats,
)


class ReflectionEngine:
    """Post-hoc decision analysis with calibration tracking and insight extraction.

    Agents record decisions with confidence levels, then record outcomes.
    The engine computes calibration error, detects patterns, and generates insights.
    """

    def __init__(self) -> None:
        self._decisions: dict[str, Decision] = {}
        self._outcomes: dict[str, Outcome] = {}
        self._insights: dict[str, Insight] = {}
        self._reflections: list[Reflection] = []

    def record_decision(self, agent_id: str, action: str, reasoning: str = "",
                        confidence: float = 0.5,
                        alternatives: list[str] | None = None,
                        context: dict | None = None) -> Decision:
        decision = Decision(
            agent_id=agent_id,
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            alternatives=tuple(alternatives or []),
            context=context or {},
        )
        self._decisions[decision.decision_id] = decision
        return decision

    def record_outcome(self, decision_id: str, success: bool,
                       actual_result: str = "",
                       expected_result: str = "") -> Outcome | None:
        decision = self._decisions.get(decision_id)
        if not decision:
            return None

        deviation = abs(decision.confidence - (1.0 if success else 0.0))
        outcome = Outcome(
            decision_id=decision_id,
            success=success,
            actual_result=actual_result,
            expected_result=expected_result,
            deviation_score=deviation,
        )
        self._outcomes[decision_id] = outcome
        return outcome

    def get_decision(self, decision_id: str) -> Decision | None:
        return self._decisions.get(decision_id)

    def get_outcome(self, decision_id: str) -> Outcome | None:
        return self._outcomes.get(decision_id)

    def get_decisions(self, agent_id: str | None = None) -> list[Decision]:
        decisions = list(self._decisions.values())
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        return decisions

    def reflect(self, agent_id: str, kind: ReflectionKind = ReflectionKind.OUTCOME_ANALYSIS,
                decision_ids: list[str] | None = None) -> Reflection:
        if decision_ids is None:
            agent_decisions = [d for d in self._decisions.values() if d.agent_id == agent_id]
            decision_ids = [d.decision_id for d in agent_decisions]

        insights = self._generate_insights(agent_id, decision_ids)
        insight_ids = tuple(i.insight_id for i in insights)

        calibration_error = self._compute_calibration_error(decision_ids)

        summary_parts = []
        if calibration_error > 0.3:
            summary_parts.append("Significant calibration gap detected.")
        if any(i.category == InsightCategory.REPEATED_MISTAKE for i in insights):
            summary_parts.append("Repeated mistakes identified.")
        if any(i.category == InsightCategory.STRATEGY_EFFECTIVE for i in insights):
            summary_parts.append("Effective strategies confirmed.")
        if not summary_parts:
            summary_parts.append("Performance within expected parameters.")

        reflection = Reflection(
            agent_id=agent_id,
            kind=kind,
            decision_ids=tuple(decision_ids),
            insights=insight_ids,
            calibration_error=calibration_error,
            summary=" ".join(summary_parts),
        )
        self._reflections.append(reflection)
        return reflection

    def get_insights(self, agent_id: str | None = None,
                     category: InsightCategory | None = None) -> list[Insight]:
        insights = list(self._insights.values())
        if agent_id:
            insights = [i for i in insights if i.agent_id == agent_id]
        if category:
            insights = [i for i in insights if i.category == category]
        return insights

    def get_calibration_error(self, agent_id: str) -> float:
        decision_ids = [
            d.decision_id for d in self._decisions.values() if d.agent_id == agent_id
        ]
        return self._compute_calibration_error(decision_ids)

    def get_confidence_level(self, agent_id: str) -> ConfidenceLevel:
        error = self.get_calibration_error(agent_id)
        if error <= 0.1:
            return ConfidenceLevel.VERY_HIGH
        elif error <= 0.2:
            return ConfidenceLevel.HIGH
        elif error <= 0.35:
            return ConfidenceLevel.MODERATE
        elif error <= 0.5:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.VERY_LOW

    def get_stats(self) -> ReflectionStats:
        agents = set(d.agent_id for d in self._decisions.values())

        outcomes = list(self._outcomes.values())
        success_rate = (
            sum(1 for o in outcomes if o.success) / len(outcomes) if outcomes else 0.0
        )

        calibration_errors = [o.deviation_score for o in outcomes]
        avg_cal = sum(calibration_errors) / len(calibration_errors) if calibration_errors else 0.0

        by_category: dict[str, int] = defaultdict(int)
        for insight in self._insights.values():
            by_category[insight.category.value] += 1

        return ReflectionStats(
            total_decisions=len(self._decisions),
            total_outcomes=len(self._outcomes),
            total_reflections=len(self._reflections),
            total_insights=len(self._insights),
            agents_reflecting=len(agents),
            avg_calibration_error=avg_cal,
            success_rate=success_rate,
            by_category=dict(by_category),
        )

    def _compute_calibration_error(self, decision_ids: list[str]) -> float:
        errors = []
        for did in decision_ids:
            outcome = self._outcomes.get(did)
            if outcome:
                errors.append(outcome.deviation_score)
        return sum(errors) / len(errors) if errors else 0.0

    def _generate_insights(self, agent_id: str, decision_ids: list[str]) -> list[Insight]:
        insights = []

        outcomes_for_decisions = [
            (self._decisions[did], self._outcomes[did])
            for did in decision_ids
            if did in self._outcomes and did in self._decisions
        ]

        if not outcomes_for_decisions:
            return insights

        failures = [(d, o) for d, o in outcomes_for_decisions if not o.success]
        successes = [(d, o) for d, o in outcomes_for_decisions if o.success]

        if len(failures) >= 3:
            actions = [d.action for d, _ in failures[-3:]]
            if len(set(actions)) == 1:
                insight = Insight(
                    agent_id=agent_id,
                    category=InsightCategory.REPEATED_MISTAKE,
                    description=f"Action '{actions[0]}' failed 3+ times consecutively.",
                    confidence=0.9,
                    source_decisions=tuple(d.decision_id for d, _ in failures[-3:]),
                )
                self._insights[insight.insight_id] = insight
                insights.append(insight)

        if len(successes) >= 3:
            insight = Insight(
                agent_id=agent_id,
                category=InsightCategory.STRATEGY_EFFECTIVE,
                description="Recent strategy showing consistent success.",
                confidence=0.7,
                source_decisions=tuple(d.decision_id for d, _ in successes[-3:]),
            )
            self._insights[insight.insight_id] = insight
            insights.append(insight)

        overconfident = [
            (d, o) for d, o in outcomes_for_decisions
            if d.confidence > 0.8 and not o.success
        ]
        if overconfident:
            insight = Insight(
                agent_id=agent_id,
                category=InsightCategory.CALIBRATION_ERROR,
                description="High confidence predictions failing — possible overconfidence.",
                confidence=0.8,
                source_decisions=tuple(d.decision_id for d, _ in overconfident),
            )
            self._insights[insight.insight_id] = insight
            insights.append(insight)

        return insights
