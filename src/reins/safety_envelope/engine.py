from __future__ import annotations

from collections import defaultdict

from reins.safety_envelope.types import (
    EnvelopeAssessment,
    EnvelopeVerdict,
    Mitigation,
    MitigationStatus,
    SafetyConstraint,
    SafetyEnvelopeStats,
    ThreatKind,
    ThreatModel,
)


class SafetyEnvelope:
    """Formal safety envelope for multi-agent systems.

    Integrates constraints, threat modeling, and mitigations into a single
    pre-flight safety assessment. Answers: "Is this agent configuration
    provably safe to run?" before execution begins.
    """

    def __init__(self) -> None:
        self._constraints: dict[str, SafetyConstraint] = {}
        self._threats: dict[str, ThreatModel] = {}
        self._mitigations: dict[str, Mitigation] = {}
        self._assessments: list[EnvelopeAssessment] = []

    def add_constraint(self, name: str, description: str = "",
                       expression: str = "",
                       agents: list[str] | None = None) -> SafetyConstraint:
        constraint = SafetyConstraint(
            name=name, description=description,
            expression=expression, agents=agents or [],
        )
        self._constraints[constraint.constraint_id] = constraint
        return constraint

    def remove_constraint(self, constraint_id: str) -> bool:
        return self._constraints.pop(constraint_id, None) is not None

    def get_constraint(self, constraint_id: str) -> SafetyConstraint | None:
        return self._constraints.get(constraint_id)

    def add_threat(self, kind: ThreatKind, description: str = "",
                   affected_agents: list[str] | None = None,
                   likelihood: float = 0.5,
                   impact: float = 0.5) -> ThreatModel:
        threat = ThreatModel(
            kind=kind, description=description,
            affected_agents=affected_agents or [],
            likelihood=likelihood, impact=impact,
        )
        self._threats[threat.threat_id] = threat
        return threat

    def add_mitigation(self, name: str, threat_id: str,
                       action: str = "") -> Mitigation:
        mitigation = Mitigation(
            name=name, threat_id=threat_id, action=action,
        )
        self._mitigations[mitigation.mitigation_id] = mitigation
        if threat_id in self._threats:
            threat = self._threats[threat_id]
            updated = threat.model_copy(update={
                "mitigations": [*threat.mitigations, mitigation.mitigation_id],
            })
            self._threats[threat_id] = updated
        return mitigation

    def trigger_mitigation(self, mitigation_id: str) -> Mitigation | None:
        m = self._mitigations.get(mitigation_id)
        if not m:
            return None
        updated = m.model_copy(update={"status": MitigationStatus.TRIGGERED})
        self._mitigations[mitigation_id] = updated
        return updated

    def assess(self, agent_ids: list[str] | None = None) -> EnvelopeAssessment:
        constraints = list(self._constraints.values())
        if agent_ids:
            constraints = [
                c for c in constraints
                if not c.agents or any(a in agent_ids for a in c.agents)
            ]

        constraints_satisfied = sum(1 for c in constraints if c.enforced)

        relevant_threats = list(self._threats.values())
        if agent_ids:
            relevant_threats = [
                t for t in relevant_threats
                if not t.affected_agents or
                any(a in agent_ids for a in t.affected_agents)
            ]

        threats_mitigated = 0
        for threat in relevant_threats:
            if threat.mitigations:
                active = any(
                    self._mitigations.get(mid) and
                    self._mitigations[mid].status in (
                        MitigationStatus.ACTIVE, MitigationStatus.TRIGGERED
                    )
                    for mid in threat.mitigations
                )
                if active:
                    threats_mitigated += 1

        risk_score = self._compute_risk(relevant_threats, threats_mitigated)

        blockers = []
        conditions = []

        unenforced = [c for c in constraints if not c.enforced]
        if unenforced:
            blockers.append(
                f"{len(unenforced)} constraint(s) not enforced"
            )

        unmitigated = len(relevant_threats) - threats_mitigated
        if unmitigated > 0:
            conditions.append(
                f"{unmitigated} threat(s) without active mitigation"
            )

        if blockers:
            verdict = EnvelopeVerdict.UNSAFE
        elif risk_score > 0.7:
            verdict = EnvelopeVerdict.UNSAFE
        elif conditions or risk_score > 0.3:
            verdict = EnvelopeVerdict.CONDITIONALLY_SAFE
        elif not constraints and not relevant_threats:
            verdict = EnvelopeVerdict.INCONCLUSIVE
        else:
            verdict = EnvelopeVerdict.SAFE

        assessment = EnvelopeAssessment(
            verdict=verdict,
            constraints_checked=len(constraints),
            constraints_satisfied=constraints_satisfied,
            threats_identified=len(relevant_threats),
            threats_mitigated=threats_mitigated,
            risk_score=risk_score,
            conditions=conditions,
            blockers=blockers,
        )
        self._assessments.append(assessment)
        return assessment

    def get_assessments(self) -> list[EnvelopeAssessment]:
        return list(self._assessments)

    def get_threats(self, kind: ThreatKind | None = None) -> list[ThreatModel]:
        threats = list(self._threats.values())
        if kind:
            threats = [t for t in threats if t.kind == kind]
        return threats

    def get_stats(self) -> SafetyEnvelopeStats:
        by_threat: dict[str, int] = defaultdict(int)
        for t in self._threats.values():
            by_threat[t.kind.value] += 1

        by_verdict: dict[str, int] = defaultdict(int)
        for a in self._assessments:
            by_verdict[a.verdict.value] += 1

        current = (self._assessments[-1].verdict
                   if self._assessments else EnvelopeVerdict.INCONCLUSIVE)
        risk = self._assessments[-1].risk_score if self._assessments else 0.0

        return SafetyEnvelopeStats(
            total_constraints=len(self._constraints),
            total_threats=len(self._threats),
            total_mitigations=len(self._mitigations),
            total_assessments=len(self._assessments),
            current_verdict=current,
            risk_score=risk,
            by_threat_kind=dict(by_threat),
            by_verdict=dict(by_verdict),
        )

    def _compute_risk(self, threats: list[ThreatModel],
                      mitigated: int) -> float:
        if not threats:
            return 0.0
        total_risk = sum(t.likelihood * t.impact for t in threats)
        max_risk = len(threats)
        raw = total_risk / max_risk if max_risk > 0 else 0.0
        mitigation_factor = mitigated / len(threats) if threats else 0.0
        return max(0.0, raw * (1.0 - mitigation_factor * 0.5))
