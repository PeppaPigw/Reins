from __future__ import annotations

from collections import defaultdict

from reins.ethics.types import (
    AlignmentLevel,
    AlignmentReport,
    EthicalEvaluation,
    EthicalFramework,
    EthicalPrinciple,
    EthicalViolation,
    EthicsStats,
    ValueDimension,
    ViolationSeverity,
)


class EthicalReasoner:
    """Moral framework for agent decision-making with value alignment verification.

    Evaluates agent actions against registered ethical principles,
    detects violations, computes alignment scores, and generates reports.
    """

    def __init__(self) -> None:
        self._principles: dict[str, EthicalPrinciple] = {}
        self._evaluations: list[EthicalEvaluation] = []
        self._violations: list[EthicalViolation] = []
        self._register_defaults()

    def register_principle(self, principle: EthicalPrinciple) -> EthicalPrinciple:
        self._principles[principle.principle_id] = principle
        return principle

    def get_principle(self, principle_id: str) -> EthicalPrinciple | None:
        return self._principles.get(principle_id)

    def get_principles(self, dimension: ValueDimension | None = None,
                       framework: EthicalFramework | None = None) -> list[EthicalPrinciple]:
        principles = list(self._principles.values())
        if dimension:
            principles = [p for p in principles if p.dimension == dimension]
        if framework:
            principles = [p for p in principles if p.framework == framework]
        return principles

    def evaluate(self, agent_id: str, action: str,
                 satisfied: list[str] | None = None,
                 violated: list[str] | None = None,
                 metadata: dict | None = None) -> EthicalEvaluation:
        satisfied_ids = satisfied or []
        violated_ids = violated or []

        score = self._compute_score(satisfied_ids, violated_ids)
        alignment = self._classify_alignment(score, violated_ids)
        reasoning = self._build_reasoning(action, satisfied_ids, violated_ids)

        evaluation = EthicalEvaluation(
            agent_id=agent_id,
            action=action,
            alignment=alignment,
            score=score,
            violated_principles=tuple(violated_ids),
            satisfied_principles=tuple(satisfied_ids),
            reasoning=reasoning,
            metadata=metadata or {},
        )
        self._evaluations.append(evaluation)

        for pid in violated_ids:
            principle = self._principles.get(pid)
            if principle:
                severity = self._determine_severity(principle)
                self._violations.append(EthicalViolation(
                    agent_id=agent_id,
                    principle_id=pid,
                    severity=severity,
                    action=action,
                    description=f"Violated: {principle.name}",
                ))

        return evaluation

    def get_evaluations(self, agent_id: str | None = None) -> list[EthicalEvaluation]:
        if agent_id:
            return [e for e in self._evaluations if e.agent_id == agent_id]
        return list(self._evaluations)

    def get_violations(self, agent_id: str | None = None,
                       severity: ViolationSeverity | None = None) -> list[EthicalViolation]:
        violations = self._violations
        if agent_id:
            violations = [v for v in violations if v.agent_id == agent_id]
        if severity:
            violations = [v for v in violations if v.severity == severity]
        return violations

    def get_alignment_report(self, agent_id: str) -> AlignmentReport:
        evals = [e for e in self._evaluations if e.agent_id == agent_id]
        violations = [v for v in self._violations if v.agent_id == agent_id]

        if not evals:
            return AlignmentReport(agent_id=agent_id)

        scores = [e.score for e in evals]
        overall_score = sum(scores) / len(scores)
        overall_alignment = self._classify_alignment(overall_score, [])

        by_dimension: dict[str, list[float]] = defaultdict(list)
        for e in evals:
            for pid in e.satisfied_principles:
                p = self._principles.get(pid)
                if p:
                    by_dimension[p.dimension.value].append(1.0)
            for pid in e.violated_principles:
                p = self._principles.get(pid)
                if p:
                    by_dimension[p.dimension.value].append(0.0)

        dim_scores = {
            dim: sum(vals) / len(vals) for dim, vals in by_dimension.items()
        }

        critical = sum(1 for v in violations if v.severity == ViolationSeverity.CRITICAL)

        if critical > 0:
            overall_alignment = AlignmentLevel.CRITICALLY_MISALIGNED

        return AlignmentReport(
            agent_id=agent_id,
            overall_alignment=overall_alignment,
            overall_score=overall_score,
            by_dimension=dim_scores,
            total_evaluations=len(evals),
            total_violations=len(violations),
            critical_violations=critical,
        )

    def check_hard_constraints(self, action: str,
                               violated_ids: list[str]) -> list[EthicalPrinciple]:
        blocked = []
        for pid in violated_ids:
            principle = self._principles.get(pid)
            if principle and principle.hard_constraint:
                blocked.append(principle)
        return blocked

    def get_stats(self) -> EthicsStats:
        by_dimension: dict[str, int] = defaultdict(int)
        for p in self._principles.values():
            by_dimension[p.dimension.value] += 1

        by_severity: dict[str, int] = defaultdict(int)
        for v in self._violations:
            by_severity[v.severity.value] += 1

        agents = {e.agent_id for e in self._evaluations}
        scores = [e.score for e in self._evaluations]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return EthicsStats(
            total_principles=len(self._principles),
            total_evaluations=len(self._evaluations),
            total_violations=len(self._violations),
            agents_evaluated=len(agents),
            avg_alignment_score=avg_score,
            by_dimension=dict(by_dimension),
            by_severity=dict(by_severity),
        )

    def _compute_score(self, satisfied: list[str], violated: list[str]) -> float:
        if not satisfied and not violated:
            return 1.0

        total_weight = 0.0
        earned_weight = 0.0

        for pid in satisfied:
            p = self._principles.get(pid)
            w = p.weight if p else 1.0
            total_weight += w
            earned_weight += w

        for pid in violated:
            p = self._principles.get(pid)
            w = p.weight if p else 1.0
            total_weight += w
            if p and p.hard_constraint:
                earned_weight -= w

        if total_weight == 0:
            return 1.0
        return max(0.0, min(1.0, earned_weight / total_weight))

    def _classify_alignment(self, score: float, violated: list[str]) -> AlignmentLevel:
        has_hard = any(
            self._principles.get(pid) and self._principles[pid].hard_constraint
            for pid in violated
        )
        if has_hard:
            return AlignmentLevel.CRITICALLY_MISALIGNED
        if score >= 0.95:
            return AlignmentLevel.FULLY_ALIGNED
        if score >= 0.8:
            return AlignmentLevel.MOSTLY_ALIGNED
        if score >= 0.5:
            return AlignmentLevel.PARTIALLY_ALIGNED
        return AlignmentLevel.MISALIGNED

    def _determine_severity(self, principle: EthicalPrinciple) -> ViolationSeverity:
        if principle.hard_constraint:
            return ViolationSeverity.CRITICAL
        if principle.weight >= 2.0:
            return ViolationSeverity.MAJOR
        if principle.weight >= 1.5:
            return ViolationSeverity.MODERATE
        if principle.weight >= 1.0:
            return ViolationSeverity.MINOR
        return ViolationSeverity.ADVISORY

    def _build_reasoning(self, action: str, satisfied: list[str], violated: list[str]) -> str:
        parts = [f"Action: {action}"]
        if satisfied:
            names = [self._principles[p].name for p in satisfied if p in self._principles]
            if names:
                parts.append(f"Satisfies: {', '.join(names[:3])}")
        if violated:
            names = [self._principles[p].name for p in violated if p in self._principles]
            if names:
                parts.append(f"Violates: {', '.join(names[:3])}")
        return ". ".join(parts)

    def _register_defaults(self) -> None:
        defaults = [
            EthicalPrinciple(
                name="Do No Harm",
                dimension=ValueDimension.NON_MALEFICENCE,
                weight=3.0,
                hard_constraint=True,
            ),
            EthicalPrinciple(
                name="Respect Autonomy",
                dimension=ValueDimension.AUTONOMY,
                weight=2.0,
            ),
            EthicalPrinciple(
                name="Be Transparent",
                dimension=ValueDimension.TRANSPARENCY,
                weight=2.0,
            ),
            EthicalPrinciple(
                name="Protect Privacy",
                dimension=ValueDimension.PRIVACY,
                weight=2.5,
                hard_constraint=True,
            ),
            EthicalPrinciple(
                name="Ensure Fairness",
                dimension=ValueDimension.JUSTICE,
                weight=2.0,
            ),
            EthicalPrinciple(
                name="Be Truthful",
                dimension=ValueDimension.TRUTHFULNESS,
                weight=2.5,
                hard_constraint=True,
            ),
            EthicalPrinciple(
                name="Accept Accountability",
                dimension=ValueDimension.ACCOUNTABILITY,
                weight=1.5,
            ),
            EthicalPrinciple(
                name="Promote Wellbeing",
                dimension=ValueDimension.BENEFICENCE,
                weight=1.5,
                framework=EthicalFramework.CONSEQUENTIALIST,
            ),
        ]
        for p in defaults:
            self._principles[p.principle_id] = p
