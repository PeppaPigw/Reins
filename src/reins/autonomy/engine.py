from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.autonomy.types import (
    AutonomyBoundary,
    AutonomyDecision,
    AutonomyLevel,
    AutonomyProfile,
    AutonomyStats,
    DecisionOutcome,
    EscalationReason,
    EscalationRequest,
)

_LEVEL_ORDER = [
    AutonomyLevel.SUPERVISED,
    AutonomyLevel.GUIDED,
    AutonomyLevel.SEMI_AUTONOMOUS,
    AutonomyLevel.AUTONOMOUS,
    AutonomyLevel.FULLY_AUTONOMOUS,
]


class AutonomyEngine:
    """Self-governance with autonomy levels, escalation, and bounded decision-making.

    Manages agent autonomy profiles, evaluates whether actions can be taken
    independently, handles escalation when boundaries are exceeded, and
    tracks decision history for trust calibration.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AutonomyProfile] = {}
        self._boundaries: dict[str, AutonomyBoundary] = {}
        self._decisions: list[AutonomyDecision] = []
        self._escalations: list[EscalationRequest] = []

    def register_agent(self, agent_id: str,
                       level: AutonomyLevel = AutonomyLevel.SUPERVISED) -> AutonomyProfile:
        profile = AutonomyProfile(agent_id=agent_id, current_level=level)
        self._profiles[agent_id] = profile
        return profile

    def get_profile(self, agent_id: str) -> AutonomyProfile | None:
        return self._profiles.get(agent_id)

    def set_level(self, agent_id: str, level: AutonomyLevel) -> AutonomyProfile | None:
        profile = self._profiles.get(agent_id)
        if not profile:
            return None
        updated = profile.model_copy(update={"current_level": level})
        self._profiles[agent_id] = updated
        return updated

    def set_boundary(self, name: str, max_level: AutonomyLevel = AutonomyLevel.GUIDED,
                     allowed_actions: list[str] | None = None,
                     forbidden_actions: list[str] | None = None,
                     risk_tolerance: float = 0.5) -> AutonomyBoundary:
        boundary = AutonomyBoundary(
            name=name,
            max_level=max_level,
            allowed_actions=tuple(allowed_actions or []),
            forbidden_actions=tuple(forbidden_actions or []),
            risk_tolerance=risk_tolerance,
        )
        self._boundaries[boundary.boundary_id] = boundary
        return boundary

    def evaluate_action(self, agent_id: str, action: str,
                        confidence: float = 0.5,
                        risk_score: float = 0.3) -> AutonomyDecision:
        profile = self._profiles.get(agent_id)
        if not profile:
            profile = self.register_agent(agent_id)

        if self._is_forbidden(action):
            decision = self._make_decision(
                agent_id, action, DecisionOutcome.DENIED,
                profile.current_level, confidence, risk_score,
                "Action is forbidden by boundary rules",
            )
            return decision

        if self._requires_escalation(profile, action, confidence, risk_score):
            decision = self._make_decision(
                agent_id, action, DecisionOutcome.ESCALATED,
                profile.current_level, confidence, risk_score,
                "Escalated due to insufficient autonomy or high risk",
            )
            self._create_escalation(agent_id, action, confidence, risk_score)
            return decision

        if self._can_auto_approve(profile, confidence, risk_score):
            decision = self._make_decision(
                agent_id, action, DecisionOutcome.APPROVED,
                profile.current_level, confidence, risk_score,
                "Auto-approved within autonomy bounds",
            )
            self._record_success(agent_id)
            return decision

        decision = self._make_decision(
            agent_id, action, DecisionOutcome.DEFERRED,
            profile.current_level, confidence, risk_score,
            "Deferred for review",
        )
        return decision

    def resolve_escalation(self, request_id: str,
                           outcome: DecisionOutcome) -> EscalationRequest | None:
        for i, req in enumerate(self._escalations):
            if req.request_id == request_id:
                resolved = req.model_copy(update={
                    "resolved": True,
                    "resolution": outcome,
                })
                self._escalations[i] = resolved
                return resolved
        return None

    def get_escalations(self, agent_id: str | None = None,
                        unresolved_only: bool = False) -> list[EscalationRequest]:
        escalations = self._escalations
        if agent_id:
            escalations = [e for e in escalations if e.agent_id == agent_id]
        if unresolved_only:
            escalations = [e for e in escalations if not e.resolved]
        return escalations

    def get_decisions(self, agent_id: str | None = None,
                      outcome: DecisionOutcome | None = None) -> list[AutonomyDecision]:
        decisions = self._decisions
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        if outcome:
            decisions = [d for d in decisions if d.outcome == outcome]
        return decisions

    def promote_agent(self, agent_id: str) -> AutonomyProfile | None:
        profile = self._profiles.get(agent_id)
        if not profile:
            return None
        idx = _LEVEL_ORDER.index(profile.current_level)
        if idx >= len(_LEVEL_ORDER) - 1:
            return profile
        new_level = _LEVEL_ORDER[idx + 1]
        updated = profile.model_copy(update={"current_level": new_level})
        self._profiles[agent_id] = updated
        return updated

    def demote_agent(self, agent_id: str) -> AutonomyProfile | None:
        profile = self._profiles.get(agent_id)
        if not profile:
            return None
        idx = _LEVEL_ORDER.index(profile.current_level)
        if idx <= 0:
            return profile
        new_level = _LEVEL_ORDER[idx - 1]
        updated = profile.model_copy(update={"current_level": new_level})
        self._profiles[agent_id] = updated
        return updated

    def get_stats(self) -> AutonomyStats:
        by_level: dict[str, int] = defaultdict(int)
        for profile in self._profiles.values():
            by_level[profile.current_level.value] += 1

        by_outcome: dict[str, int] = defaultdict(int)
        for decision in self._decisions:
            by_outcome[decision.outcome.value] += 1

        confidences = [d.confidence for d in self._decisions]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        auto_approved = by_outcome.get(DecisionOutcome.APPROVED.value, 0)

        return AutonomyStats(
            total_agents=len(self._profiles),
            total_decisions=len(self._decisions),
            total_escalations=len(self._escalations),
            auto_approved=auto_approved,
            avg_confidence=avg_conf,
            by_level=dict(by_level),
            by_outcome=dict(by_outcome),
        )

    def _is_forbidden(self, action: str) -> bool:
        for boundary in self._boundaries.values():
            if action in boundary.forbidden_actions:
                return True
        return False

    def _requires_escalation(self, profile: AutonomyProfile, action: str,
                             confidence: float, risk_score: float) -> bool:
        if profile.current_level == AutonomyLevel.SUPERVISED:
            return True

        for boundary in self._boundaries.values():
            level_idx = _LEVEL_ORDER.index(profile.current_level)
            max_idx = _LEVEL_ORDER.index(boundary.max_level)
            if level_idx > max_idx:
                continue
            if risk_score > boundary.risk_tolerance:
                return True

        if confidence < 0.3:
            return True

        return False

    def _can_auto_approve(self, profile: AutonomyProfile,
                          confidence: float, risk_score: float) -> bool:
        level_idx = _LEVEL_ORDER.index(profile.current_level)
        if level_idx >= 3:
            return True
        if level_idx >= 2 and confidence >= 0.7 and risk_score <= 0.3:
            return True
        if level_idx >= 1 and confidence >= 0.9 and risk_score <= 0.1:
            return True
        return False

    def _make_decision(self, agent_id: str, action: str, outcome: DecisionOutcome,
                       level: AutonomyLevel, confidence: float,
                       risk_score: float, reasoning: str) -> AutonomyDecision:
        decision = AutonomyDecision(
            agent_id=agent_id,
            action=action,
            outcome=outcome,
            autonomy_level=level,
            confidence=confidence,
            risk_score=risk_score,
            reasoning=reasoning,
        )
        self._decisions.append(decision)
        return decision

    def _create_escalation(self, agent_id: str, action: str,
                           confidence: float, risk_score: float) -> EscalationRequest:
        if confidence < 0.3:
            reason = EscalationReason.UNCERTAINTY
        elif risk_score > 0.7:
            reason = EscalationReason.RISK_THRESHOLD
        else:
            reason = EscalationReason.NOVEL_SITUATION

        escalation = EscalationRequest(
            agent_id=agent_id,
            action=action,
            reason=reason,
            context={"confidence": confidence, "risk_score": risk_score},
        )
        self._escalations.append(escalation)
        return escalation

    def _record_success(self, agent_id: str) -> None:
        profile = self._profiles.get(agent_id)
        if not profile:
            return
        new_decisions = profile.decisions_made + 1
        agent_decisions = [d for d in self._decisions if d.agent_id == agent_id]
        successes = sum(1 for d in agent_decisions if d.outcome == DecisionOutcome.APPROVED)
        success_rate = successes / new_decisions if new_decisions > 0 else 0.0
        self._profiles[agent_id] = profile.model_copy(update={
            "decisions_made": new_decisions,
            "success_rate": success_rate,
        })
