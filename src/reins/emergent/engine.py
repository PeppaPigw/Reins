from __future__ import annotations

from collections import defaultdict

from reins.emergent.types import (
    AgentAction,
    CollectiveMetric,
    EmergentPattern,
    EmergentStats,
    PatternKind,
    Severity,
)


class EmergentDetector:
    """Detects emergent collective behaviors in multi-agent systems.

    Monitors agent actions for herding, information cascades, feedback loops,
    synchronization, and polarization. Uses statistical analysis to distinguish
    genuine emergent phenomena from coincidence.
    """

    def __init__(self, window_size: int = 50, herding_threshold: float = 0.7,
                 cascade_threshold: int = 3) -> None:
        self._window_size = window_size
        self._herding_threshold = herding_threshold
        self._cascade_threshold = cascade_threshold
        self._actions: list[AgentAction] = []
        self._patterns: list[EmergentPattern] = []
        self._metrics: list[CollectiveMetric] = []

    def record_action(self, agent_id: str, action_type: str,
                      target: str = "", value: float = 0.0) -> AgentAction:
        action = AgentAction(
            agent_id=agent_id, action_type=action_type,
            target=target, value=value,
        )
        self._actions.append(action)
        self._check_patterns()
        return action

    def record_batch(self, actions: list[tuple[str, str, str, float]]) -> list[AgentAction]:
        results = []
        for agent_id, action_type, target, value in actions:
            action = AgentAction(
                agent_id=agent_id, action_type=action_type,
                target=target, value=value,
            )
            self._actions.append(action)
            results.append(action)
        self._check_patterns()
        return results

    def get_patterns(self, kind: PatternKind | None = None,
                     severity: Severity | None = None) -> list[EmergentPattern]:
        patterns = self._patterns
        if kind:
            patterns = [p for p in patterns if p.kind == kind]
        if severity:
            patterns = [p for p in patterns if p.severity == severity]
        return patterns

    def compute_diversity(self) -> float:
        recent = self._actions[-self._window_size:]
        if not recent:
            return 1.0
        action_types = set(a.action_type for a in recent)
        agents = set(a.agent_id for a in recent)
        if not agents:
            return 1.0
        return len(action_types) / len(agents) if len(agents) > 0 else 1.0

    def compute_synchronization(self) -> float:
        recent = self._actions[-self._window_size:]
        if len(recent) < 2:
            return 0.0
        type_counts: dict[str, int] = defaultdict(int)
        for a in recent:
            type_counts[a.action_type] += 1
        max_count = max(type_counts.values())
        return max_count / len(recent)

    def compute_polarization(self) -> float:
        recent = self._actions[-self._window_size:]
        if not recent:
            return 0.0
        values = [a.value for a in recent if a.value != 0.0]
        if len(values) < 2:
            return 0.0
        positive = sum(1 for v in values if v > 0)
        negative = sum(1 for v in values if v < 0)
        total = positive + negative
        if total == 0:
            return 0.0
        balance = abs(positive - negative) / total
        return 1.0 - balance

    def get_metrics(self) -> list[CollectiveMetric]:
        agents = set(a.agent_id for a in self._actions)
        metrics = [
            CollectiveMetric(name="diversity", value=self.compute_diversity(),
                             agents_sampled=len(agents)),
            CollectiveMetric(name="synchronization", value=self.compute_synchronization(),
                             agents_sampled=len(agents)),
            CollectiveMetric(name="polarization", value=self.compute_polarization(),
                             agents_sampled=len(agents)),
        ]
        return metrics

    def get_stats(self) -> EmergentStats:
        agents = set(a.agent_id for a in self._actions)

        by_kind: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        confidences = []
        for p in self._patterns:
            by_kind[p.kind.value] += 1
            by_severity[p.severity.value] += 1
            confidences.append(p.confidence)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return EmergentStats(
            total_actions=len(self._actions),
            total_patterns=len(self._patterns),
            agents_monitored=len(agents),
            by_pattern_kind=dict(by_kind),
            by_severity=dict(by_severity),
            avg_confidence=avg_conf,
        )

    def _check_patterns(self) -> None:
        recent = self._actions[-self._window_size:]
        if len(recent) < 5:
            return

        self._detect_herding(recent)
        self._detect_cascade(recent)
        self._detect_feedback_loop(recent)

    def _detect_herding(self, actions: list[AgentAction]) -> None:
        type_counts: dict[str, list[str]] = defaultdict(list)
        for a in actions:
            type_counts[a.action_type].append(a.agent_id)

        for action_type, agents in type_counts.items():
            unique_agents = set(agents)
            all_agents = set(a.agent_id for a in actions)
            ratio = len(unique_agents) / len(all_agents) if all_agents else 0

            if ratio >= self._herding_threshold and len(unique_agents) >= 3:
                already_detected = any(
                    p.kind == PatternKind.HERDING and
                    set(p.agents_involved) == unique_agents
                    for p in self._patterns[-10:]
                )
                if not already_detected:
                    pattern = EmergentPattern(
                        kind=PatternKind.HERDING,
                        severity=Severity.CONCERNING if ratio > 0.9 else Severity.NOTABLE,
                        agents_involved=tuple(sorted(unique_agents)),
                        description=f"{len(unique_agents)} agents converging on '{action_type}'.",
                        confidence=ratio,
                        evidence_count=len(agents),
                    )
                    self._patterns.append(pattern)

    def _detect_cascade(self, actions: list[AgentAction]) -> None:
        if len(actions) < self._cascade_threshold:
            return

        for i in range(len(actions) - self._cascade_threshold + 1):
            window = actions[i:i + self._cascade_threshold]
            if all(a.action_type == window[0].action_type for a in window):
                agents = [a.agent_id for a in window]
                if len(set(agents)) >= self._cascade_threshold:
                    already = any(
                        p.kind == PatternKind.CASCADE and
                        p.description.startswith(f"Cascade of '{window[0].action_type}'")
                        for p in self._patterns[-5:]
                    )
                    if not already:
                        pattern = EmergentPattern(
                            kind=PatternKind.CASCADE,
                            severity=Severity.NOTABLE,
                            agents_involved=tuple(agents),
                            description=f"Cascade of '{window[0].action_type}' across {len(set(agents))} agents.",
                            confidence=0.7,
                            evidence_count=len(window),
                        )
                        self._patterns.append(pattern)
                    break

    def _detect_feedback_loop(self, actions: list[AgentAction]) -> None:
        agent_sequences: dict[str, list[str]] = defaultdict(list)
        for a in actions:
            agent_sequences[a.agent_id].append(a.action_type)

        for agent_id, seq in agent_sequences.items():
            if len(seq) < 4:
                continue
            for pattern_len in range(2, min(5, len(seq) // 2 + 1)):
                pattern_candidate = tuple(seq[-pattern_len:])
                prev = tuple(seq[-(2 * pattern_len):-pattern_len])
                if pattern_candidate == prev:
                    already = any(
                        p.kind == PatternKind.FEEDBACK_LOOP and
                        agent_id in p.agents_involved
                        for p in self._patterns[-5:]
                    )
                    if not already:
                        pattern = EmergentPattern(
                            kind=PatternKind.FEEDBACK_LOOP,
                            severity=Severity.CONCERNING,
                            agents_involved=(agent_id,),
                            description=f"Agent '{agent_id}' in repeating loop: {list(pattern_candidate)}.",
                            confidence=0.8,
                            evidence_count=pattern_len * 2,
                        )
                        self._patterns.append(pattern)
                    break
