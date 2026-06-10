from __future__ import annotations

from collections import defaultdict

from reins.blame.types import (
    AgentAction,
    BlameAssignment,
    BlameLevel,
    BlameReport,
    BlameStats,
    FailureEvent,
    FailureKind,
)


class BlameEngine:
    """Automatic blame attribution for multi-agent failures.

    Traces causal chains through agent actions to identify root causes.
    Assigns blame levels (root_cause, contributing, propagating, bystander)
    with confidence scores based on causal proximity and action effects.
    """

    def __init__(self) -> None:
        self._actions: list[AgentAction] = []
        self._failures: list[FailureEvent] = []
        self._reports: list[BlameReport] = []

    def record_action(self, agent_id: str, action_type: str,
                      caused_by: str = "", effects: list[str] | None = None,
                      success: bool = True, error: str = "") -> AgentAction:
        action = AgentAction(
            agent_id=agent_id,
            action_type=action_type,
            caused_by=caused_by,
            effects=effects or [],
            success=success,
            error=error,
        )
        self._actions.append(action)
        return action

    def record_failure(self, kind: FailureKind, agent_id: str,
                       message: str = "",
                       action_id: str = "") -> FailureEvent:
        failure = FailureEvent(
            kind=kind, agent_id=agent_id,
            message=message, action_id=action_id,
        )
        self._failures.append(failure)
        return failure

    def analyze(self, failure_id: str) -> BlameReport:
        failure = next((f for f in self._failures if f.failure_id == failure_id), None)
        if not failure:
            report = BlameReport(failure_id=failure_id)
            self._reports.append(report)
            return report

        causal_chain = self._trace_causal_chain(failure)
        assignments = self._assign_blame(failure, causal_chain)

        root_agent = ""
        for a in assignments:
            if a.level == BlameLevel.ROOT_CAUSE:
                root_agent = a.agent_id
                break

        report = BlameReport(
            failure_id=failure_id,
            root_cause_agent=root_agent,
            assignments=assignments,
            causal_depth=len(causal_chain),
        )
        self._reports.append(report)
        return report

    def get_failures(self, agent_id: str | None = None,
                     kind: FailureKind | None = None) -> list[FailureEvent]:
        failures = self._failures
        if agent_id:
            failures = [f for f in failures if f.agent_id == agent_id]
        if kind:
            failures = [f for f in failures if f.kind == kind]
        return failures

    def get_reports(self, agent_id: str | None = None) -> list[BlameReport]:
        if agent_id:
            return [r for r in self._reports if r.root_cause_agent == agent_id]
        return list(self._reports)

    def get_agent_blame_score(self, agent_id: str) -> float:
        score = 0.0
        for report in self._reports:
            for assignment in report.assignments:
                if assignment.agent_id == agent_id:
                    if assignment.level == BlameLevel.ROOT_CAUSE:
                        score += 1.0
                    elif assignment.level == BlameLevel.CONTRIBUTING:
                        score += 0.5
                    elif assignment.level == BlameLevel.PROPAGATING:
                        score += 0.2
        return score

    def get_stats(self) -> BlameStats:
        by_kind: dict[str, int] = defaultdict(int)
        for f in self._failures:
            by_kind[f.kind.value] += 1

        by_level: dict[str, int] = defaultdict(int)
        blame_by_agent: dict[str, int] = defaultdict(int)
        for report in self._reports:
            for a in report.assignments:
                by_level[a.level.value] += 1
                if a.level in (BlameLevel.ROOT_CAUSE, BlameLevel.CONTRIBUTING):
                    blame_by_agent[a.agent_id] += 1

        return BlameStats(
            total_failures=len(self._failures),
            total_reports=len(self._reports),
            by_failure_kind=dict(by_kind),
            by_blame_level=dict(by_level),
            blame_by_agent=dict(blame_by_agent),
        )

    def _trace_causal_chain(self, failure: FailureEvent) -> list[AgentAction]:
        chain: list[AgentAction] = []

        if failure.action_id:
            action = next(
                (a for a in self._actions if a.action_id == failure.action_id), None
            )
            if action:
                chain.append(action)
                self._trace_back(action, chain, depth=10)
        else:
            failed_actions = [
                a for a in self._actions
                if a.agent_id == failure.agent_id and not a.success
            ]
            if failed_actions:
                chain.append(failed_actions[-1])
                self._trace_back(failed_actions[-1], chain, depth=10)

        return chain

    def _trace_back(self, action: AgentAction,
                    chain: list[AgentAction], depth: int) -> None:
        if depth <= 0 or not action.caused_by:
            return
        cause = next(
            (a for a in self._actions if a.action_id == action.caused_by), None
        )
        if cause and cause not in chain:
            chain.append(cause)
            self._trace_back(cause, chain, depth - 1)

    def _assign_blame(self, failure: FailureEvent,
                      chain: list[AgentAction]) -> list[BlameAssignment]:
        assignments: list[BlameAssignment] = []
        seen_agents: set[str] = set()

        if not chain:
            assignments.append(BlameAssignment(
                failure_id=failure.failure_id,
                agent_id=failure.agent_id,
                level=BlameLevel.ROOT_CAUSE,
                confidence=0.5,
                evidence=[f"Direct failure on agent '{failure.agent_id}'"],
            ))
            return assignments

        for i, action in enumerate(chain):
            if action.agent_id in seen_agents:
                continue
            seen_agents.add(action.agent_id)

            if i == 0 and not action.success:
                level = BlameLevel.ROOT_CAUSE
                confidence = 0.9
            elif i == 0:
                level = BlameLevel.CONTRIBUTING
                confidence = 0.7
            elif not action.success:
                level = BlameLevel.CONTRIBUTING
                confidence = max(0.3, 0.8 - i * 0.15)
            else:
                level = BlameLevel.PROPAGATING
                confidence = max(0.2, 0.6 - i * 0.1)

            chain_ids = [a.action_id for a in chain[:i + 1]]
            evidence = []
            if not action.success:
                evidence.append(f"Action failed: {action.error or action.action_type}")
            if action.effects:
                evidence.append(f"Effects: {', '.join(action.effects)}")

            assignments.append(BlameAssignment(
                failure_id=failure.failure_id,
                agent_id=action.agent_id,
                level=level,
                confidence=confidence,
                evidence=evidence,
                causal_chain=chain_ids,
            ))

        return assignments
