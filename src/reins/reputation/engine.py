from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.reputation.types import (
    AgentReputation,
    Endorsement,
    FeedbackKind,
    ReputationEvent,
    ReputationPolicy,
    ReputationStats,
    ReputationTier,
)

_TIER_THRESHOLDS = [
    (90.0, ReputationTier.ELITE),
    (70.0, ReputationTier.TRUSTED),
    (40.0, ReputationTier.ESTABLISHED),
    (20.0, ReputationTier.NEWCOMER),
    (0.0, ReputationTier.UNTRUSTED),
]


class ReputationEngine:
    """Trust-based reputation scoring with history, decay, and peer endorsements.

    Tracks agent reputation through events, computes tier classifications,
    manages endorsement networks, and enforces reputation-gated policies.
    """

    def __init__(self, decay_rate: float = 0.01) -> None:
        self._reputations: dict[str, AgentReputation] = {}
        self._events: list[ReputationEvent] = []
        self._endorsements: list[Endorsement] = []
        self._policies: dict[str, ReputationPolicy] = {}
        self._decay_rate = decay_rate

    def get_reputation(self, agent_id: str) -> AgentReputation:
        if agent_id not in self._reputations:
            score = 50.0
            tier = self._compute_tier(score)
            self._reputations[agent_id] = AgentReputation(
                agent_id=agent_id, score=score, tier=tier,
            )
        return self._reputations[agent_id]

    def record_success(self, agent_id: str, points: float = 5.0,
                       reason: str = "") -> ReputationEvent:
        return self._apply_event(agent_id, FeedbackKind.ACHIEVEMENT, points, reason)

    def record_failure(self, agent_id: str, points: float = 3.0,
                       reason: str = "") -> ReputationEvent:
        return self._apply_event(agent_id, FeedbackKind.PENALTY, -points, reason)

    def endorse(self, from_agent: str, to_agent: str,
                weight: float = 1.0, category: str = "") -> Endorsement:
        endorsement = Endorsement(
            from_agent=from_agent,
            to_agent=to_agent,
            weight=weight,
            category=category,
        )
        self._endorsements.append(endorsement)

        bonus = weight * 2.0
        self._apply_event(to_agent, FeedbackKind.ENDORSEMENT, bonus,
                          f"endorsed by {from_agent}", source_agent=from_agent)
        return endorsement

    def warn(self, agent_id: str, reason: str = "",
             source_agent: str = "") -> ReputationEvent:
        return self._apply_event(agent_id, FeedbackKind.WARNING, -2.0, reason, source_agent)

    def apply_decay(self) -> int:
        affected = 0
        for agent_id, rep in self._reputations.items():
            if rep.score > 50.0:
                decay_amount = (rep.score - 50.0) * self._decay_rate
                if decay_amount >= 0.01:
                    self._apply_event(agent_id, FeedbackKind.DECAY, -decay_amount, "periodic decay")
                    affected += 1
        return affected

    def get_tier(self, agent_id: str) -> ReputationTier:
        rep = self.get_reputation(agent_id)
        return rep.tier

    def check_permission(self, agent_id: str, action: str) -> bool:
        policy = self._policies.get(action)
        if not policy:
            return True
        rep = self.get_reputation(agent_id)
        if rep.score < policy.min_score_for_action:
            return False
        tier_order = [t for _, t in _TIER_THRESHOLDS]
        agent_tier_idx = tier_order.index(rep.tier) if rep.tier in tier_order else len(tier_order)
        required_idx = tier_order.index(policy.required_tier) if policy.required_tier in tier_order else 0
        return agent_tier_idx <= required_idx

    def set_policy(self, action: str, min_score: float = 0.0,
                   required_tier: ReputationTier = ReputationTier.NEWCOMER) -> ReputationPolicy:
        policy = ReputationPolicy(
            action=action,
            min_score_for_action=min_score,
            required_tier=required_tier,
        )
        self._policies[action] = policy
        return policy

    def get_events(self, agent_id: str | None = None,
                   kind: FeedbackKind | None = None) -> list[ReputationEvent]:
        events = self._events
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        if kind:
            events = [e for e in events if e.kind == kind]
        return events

    def get_endorsements(self, to_agent: str | None = None,
                         from_agent: str | None = None) -> list[Endorsement]:
        endorsements = self._endorsements
        if to_agent:
            endorsements = [e for e in endorsements if e.to_agent == to_agent]
        if from_agent:
            endorsements = [e for e in endorsements if e.from_agent == from_agent]
        return endorsements

    def get_leaderboard(self, top_n: int = 10) -> list[AgentReputation]:
        reps = sorted(self._reputations.values(), key=lambda r: r.score, reverse=True)
        return reps[:top_n]

    def get_stats(self) -> ReputationStats:
        by_tier: dict[str, int] = defaultdict(int)
        total_score = 0.0
        for rep in self._reputations.values():
            by_tier[rep.tier.value] += 1
            total_score += rep.score

        avg_score = total_score / len(self._reputations) if self._reputations else 0.0

        return ReputationStats(
            total_agents=len(self._reputations),
            avg_score=avg_score,
            total_events=len(self._events),
            total_endorsements=len(self._endorsements),
            by_tier=dict(by_tier),
        )

    def _apply_event(self, agent_id: str, kind: FeedbackKind, delta: float,
                     reason: str = "", source_agent: str = "") -> ReputationEvent:
        event = ReputationEvent(
            agent_id=agent_id,
            kind=kind,
            delta=delta,
            reason=reason,
            source_agent=source_agent,
        )
        self._events.append(event)

        rep = self.get_reputation(agent_id)
        new_score = max(0.0, min(100.0, rep.score + delta))
        new_tier = self._compute_tier(new_score)

        updates: dict = {
            "score": new_score,
            "tier": new_tier,
            "last_activity": datetime.now(UTC),
        }

        if kind == FeedbackKind.ENDORSEMENT:
            updates["total_endorsements"] = rep.total_endorsements + 1
        elif kind == FeedbackKind.PENALTY:
            updates["total_penalties"] = rep.total_penalties + 1
            updates["streak"] = 0
        elif kind == FeedbackKind.ACHIEVEMENT:
            updates["streak"] = rep.streak + 1

        self._reputations[agent_id] = rep.model_copy(update=updates)
        return event

    def _compute_tier(self, score: float) -> ReputationTier:
        for threshold, tier in _TIER_THRESHOLDS:
            if score >= threshold:
                return tier
        return ReputationTier.UNTRUSTED
