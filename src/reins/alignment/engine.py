from __future__ import annotations

from collections import defaultdict

from reins.alignment.types import (
    AlignmentCheck,
    AlignmentStats,
    AlignmentStatus,
    Preference,
    PreferenceSource,
    Value,
    ValueKind,
)


class AlignmentEngine:
    """Ensures agent behavior stays aligned with human values and preferences.

    Implements value-weighted alignment scoring, preference learning from
    pairwise comparisons, constraint checking, and drift detection.
    """

    def __init__(self, alignment_threshold: float = 0.7,
                 drift_threshold: float = 0.5) -> None:
        self._alignment_threshold = alignment_threshold
        self._drift_threshold = drift_threshold
        self._values: dict[str, Value] = {}
        self._preferences: list[Preference] = []
        self._checks: list[AlignmentCheck] = []

    def register_value(self, kind: ValueKind, weight: float = 1.0,
                       description: str = "",
                       constraints: list[str] | None = None) -> Value:
        value = Value(
            kind=kind, weight=weight,
            description=description,
            constraints=tuple(constraints or []),
        )
        self._values[value.value_id] = value
        return value

    def add_preference(self, preferred: str, dispreferred: str,
                       strength: float = 1.0,
                       source: PreferenceSource = PreferenceSource.EXPLICIT,
                       context: dict | None = None) -> Preference:
        pref = Preference(
            action_preferred=preferred,
            action_dispreferred=dispreferred,
            strength=strength,
            source=source,
            context=context or {},
        )
        self._preferences.append(pref)
        return pref

    def check_alignment(self, agent_id: str, action: str,
                        value_scores: dict[str, float] | None = None) -> AlignmentCheck:
        scores = value_scores or {}
        violations = []
        satisfied = []

        total_score = 0.0
        total_weight = 0.0

        for vid, value in self._values.items():
            score = scores.get(value.kind.value, 0.5)
            weighted = score * value.weight
            total_score += weighted
            total_weight += value.weight

            if score < 0.3:
                violations.append(f"{value.kind.value}: {score:.2f}")
            elif score >= 0.7:
                satisfied.append(value.kind.value)

            for constraint in value.constraints:
                if constraint.lower() in action.lower():
                    violations.append(f"Constraint violated: {constraint}")

        alignment_score = total_score / total_weight if total_weight > 0 else 0.5

        pref_penalty = self._compute_preference_penalty(action)
        alignment_score = max(0.0, alignment_score - pref_penalty)

        if alignment_score >= self._alignment_threshold:
            status = AlignmentStatus.ALIGNED
        elif alignment_score >= self._drift_threshold:
            status = AlignmentStatus.DRIFTING
        elif alignment_score > 0:
            status = AlignmentStatus.MISALIGNED
        else:
            status = AlignmentStatus.UNCERTAIN

        check = AlignmentCheck(
            action=action, agent_id=agent_id,
            status=status, score=alignment_score,
            violations=tuple(violations),
            satisfied_values=tuple(satisfied),
        )
        self._checks.append(check)
        return check

    def is_aligned(self, agent_id: str, action: str,
                   value_scores: dict[str, float] | None = None) -> bool:
        check = self.check_alignment(agent_id, action, value_scores)
        return check.status == AlignmentStatus.ALIGNED

    def get_violations(self, agent_id: str | None = None) -> list[AlignmentCheck]:
        checks = self._checks
        if agent_id:
            checks = [c for c in checks if c.agent_id == agent_id]
        return [c for c in checks if c.violations]

    def detect_drift(self, agent_id: str, window: int = 10) -> float:
        agent_checks = [c for c in self._checks if c.agent_id == agent_id]
        if len(agent_checks) < 2:
            return 0.0

        recent = agent_checks[-window:]
        if len(recent) < 2:
            return 0.0

        mid = len(recent) // 2
        first_half = recent[:mid]
        second_half = recent[mid:]

        avg_first = sum(c.score for c in first_half) / len(first_half)
        avg_second = sum(c.score for c in second_half) / len(second_half)

        return max(0.0, avg_first - avg_second)

    def get_value_scores(self) -> dict[str, float]:
        value_totals: dict[str, list[float]] = defaultdict(list)
        for check in self._checks:
            for vid, value in self._values.items():
                if value.kind.value in check.satisfied_values:
                    value_totals[value.kind.value].append(1.0)
                elif any(value.kind.value in v for v in check.violations):
                    value_totals[value.kind.value].append(0.0)

        return {
            k: sum(v) / len(v) if v else 0.5
            for k, v in value_totals.items()
        }

    def get_stats(self) -> AlignmentStats:
        aligned = sum(1 for c in self._checks if c.status == AlignmentStatus.ALIGNED)
        misaligned = sum(1 for c in self._checks if c.status == AlignmentStatus.MISALIGNED)
        drifting = sum(1 for c in self._checks if c.status == AlignmentStatus.DRIFTING)

        scores = [c.score for c in self._checks]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        by_value = self.get_value_scores()

        return AlignmentStats(
            total_checks=len(self._checks),
            aligned=aligned,
            misaligned=misaligned,
            drifting=drifting,
            total_values=len(self._values),
            total_preferences=len(self._preferences),
            avg_alignment_score=avg_score,
            by_value=by_value,
        )

    def _compute_preference_penalty(self, action: str) -> float:
        penalty = 0.0
        for pref in self._preferences:
            if pref.action_dispreferred.lower() in action.lower():
                penalty += 0.1 * pref.strength
        return min(0.5, penalty)
