from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.trust.types import (
    AutonomyLevel,
    ReputationEvent,
    ReputationEventKind,
    TrustDecay,
    TrustDecision,
    TrustDimension,
    TrustProfile,
    TrustScore,
    TrustThresholds,
)


class TrustEngine:
    """Tracks agent reputation across dimensions and grants progressive autonomy.

    Agents start supervised and earn autonomy through consistent positive outcomes.
    Violations cause immediate trust reduction with slow recovery.
    """

    def __init__(self, thresholds: TrustThresholds | None = None) -> None:
        self._thresholds = thresholds or TrustThresholds()
        self._scores: dict[str, dict[TrustDimension, _MutableScore]] = defaultdict(
            lambda: {d: _MutableScore() for d in TrustDimension}
        )
        self._events: dict[str, list[ReputationEvent]] = defaultdict(list)

    def record_event(self, event: ReputationEvent) -> TrustProfile:
        self._events[event.agent_id].append(event)
        score = self._scores[event.agent_id][event.dimension]

        delta = self._compute_delta(event)
        score.score = max(0.0, min(1.0, score.score + delta))
        score.sample_count += 1
        score.last_updated = event.timestamp

        return self.get_profile(event.agent_id)

    def get_profile(self, agent_id: str) -> TrustProfile:
        if agent_id not in self._scores:
            return TrustProfile(agent_id=agent_id)

        scores = tuple(
            TrustScore(
                dimension=dim,
                score=ms.score,
                confidence=self._compute_confidence(ms.sample_count),
                sample_count=ms.sample_count,
                last_updated=ms.last_updated,
            )
            for dim, ms in self._scores[agent_id].items()
        )

        composite = self._composite_score(agent_id)
        autonomy = self._determine_autonomy(composite)
        events = self._events.get(agent_id, [])

        return TrustProfile(
            agent_id=agent_id,
            scores=scores,
            autonomy_level=autonomy,
            total_events=len(events),
            last_event_at=events[-1].timestamp if events else None,
        )

    def evaluate(self, agent_id: str, required_dimension: TrustDimension | None = None,
                 min_autonomy: AutonomyLevel = AutonomyLevel.GUIDED) -> TrustDecision:
        profile = self.get_profile(agent_id)
        composite = self._composite_score(agent_id)
        current_autonomy = profile.autonomy_level

        autonomy_rank = {
            AutonomyLevel.SUPERVISED: 0,
            AutonomyLevel.GUIDED: 1,
            AutonomyLevel.AUTONOMOUS: 2,
            AutonomyLevel.FULLY_TRUSTED: 3,
        }

        allowed = autonomy_rank[current_autonomy] >= autonomy_rank[min_autonomy]

        limiting = None
        if required_dimension and agent_id in self._scores:
            dim_score = self._scores[agent_id][required_dimension].score
            if dim_score < self._thresholds.guided_threshold:
                allowed = False
                limiting = required_dimension

        reason = self._build_reason(allowed, current_autonomy, min_autonomy, limiting)

        return TrustDecision(
            agent_id=agent_id,
            allowed=allowed,
            autonomy_level=current_autonomy,
            composite_score=composite,
            limiting_dimension=limiting,
            reason=reason,
        )

    def decay_scores(self, reference_time: datetime | None = None) -> dict[str, float]:
        ref = reference_time or datetime.now(UTC)
        deltas: dict[str, float] = {}

        if self._thresholds.decay == TrustDecay.NONE:
            return deltas

        for agent_id, dimensions in self._scores.items():
            total_decay = 0.0
            for dim, ms in dimensions.items():
                age_hours = (ref - ms.last_updated).total_seconds() / 3600.0
                if age_hours <= 0:
                    continue

                if self._thresholds.decay == TrustDecay.LINEAR:
                    factor = max(0.0, 1.0 - age_hours / (self._thresholds.decay_half_life_hours * 2))
                else:
                    factor = math.exp(-age_hours / self._thresholds.decay_half_life_hours * math.log(2))

                new_score = 0.5 + (ms.score - 0.5) * factor
                decay_amount = ms.score - new_score
                ms.score = new_score
                total_decay += abs(decay_amount)

            if total_decay > 0:
                deltas[agent_id] = total_decay

        return deltas

    def get_stats(self) -> dict[str, Any]:
        if not self._scores:
            return {"total_agents": 0, "total_events": 0}

        total_events = sum(len(evts) for evts in self._events.values())
        autonomy_dist: dict[str, int] = defaultdict(int)
        for agent_id in self._scores:
            profile = self.get_profile(agent_id)
            autonomy_dist[profile.autonomy_level.value] += 1

        return {
            "total_agents": len(self._scores),
            "total_events": total_events,
            "autonomy_distribution": dict(autonomy_dist),
            "avg_composite": sum(self._composite_score(a) for a in self._scores) / len(self._scores),
        }

    def _compute_delta(self, event: ReputationEvent) -> float:
        t = self._thresholds
        if event.kind == ReputationEventKind.SUCCESS:
            return t.success_reward * event.magnitude
        elif event.kind == ReputationEventKind.FAILURE:
            return -t.failure_penalty * event.magnitude
        elif event.kind == ReputationEventKind.VIOLATION:
            return -t.violation_penalty * event.magnitude
        elif event.kind == ReputationEventKind.TIMEOUT:
            return -t.failure_penalty * 0.5 * event.magnitude
        elif event.kind == ReputationEventKind.RECOVERY:
            return t.recovery_bonus * event.magnitude
        elif event.kind == ReputationEventKind.ESCALATION:
            return -t.failure_penalty * 0.3 * event.magnitude
        return 0.0

    def _composite_score(self, agent_id: str) -> float:
        if agent_id not in self._scores:
            return 0.5
        dimensions = self._scores[agent_id]
        weights = {
            TrustDimension.SAFETY: 2.0,
            TrustDimension.CORRECTNESS: 1.5,
            TrustDimension.COMPLIANCE: 1.2,
            TrustDimension.RELIABILITY: 1.0,
            TrustDimension.EFFICIENCY: 0.8,
        }
        total_weight = sum(weights.values())
        weighted_sum = sum(dimensions[d].score * weights[d] for d in TrustDimension)
        return weighted_sum / total_weight

    def _determine_autonomy(self, composite: float) -> AutonomyLevel:
        t = self._thresholds
        if composite >= t.fully_trusted_threshold:
            return AutonomyLevel.FULLY_TRUSTED
        elif composite >= t.autonomous_threshold:
            return AutonomyLevel.AUTONOMOUS
        elif composite >= t.guided_threshold:
            return AutonomyLevel.GUIDED
        return AutonomyLevel.SUPERVISED

    def _compute_confidence(self, sample_count: int) -> float:
        min_samples = self._thresholds.min_samples_for_confidence
        if sample_count >= min_samples:
            return 1.0
        return sample_count / min_samples

    def _build_reason(self, allowed: bool, current: AutonomyLevel,
                      required: AutonomyLevel, limiting: TrustDimension | None) -> str:
        if allowed:
            return f"Agent has {current.value} autonomy (meets {required.value} requirement)"
        if limiting:
            return f"Blocked: {limiting.value} score below threshold"
        return f"Insufficient autonomy: {current.value} < required {required.value}"


class _MutableScore:
    __slots__ = ("score", "sample_count", "last_updated")

    def __init__(self) -> None:
        self.score = 0.5
        self.sample_count = 0
        self.last_updated = datetime.now(UTC)
