from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.metacognition.types import (
    CognitiveSignal,
    CognitiveState,
    Intervention,
    InterventionKind,
    MetacognitionConfig,
    MetacognitionStats,
    ReasoningStep,
    SignalSource,
)


class MetacognitionEngine:
    """Self-monitoring of reasoning quality with automatic corrective interventions.

    Detects confusion, loops, hallucination patterns, overconfidence, and
    stuckness by analyzing reasoning step sequences and applying interventions.
    """

    def __init__(self, config: MetacognitionConfig | None = None) -> None:
        self._config = config or MetacognitionConfig()
        self._steps: dict[str, list[ReasoningStep]] = defaultdict(list)
        self._signals: list[CognitiveSignal] = []
        self._interventions: list[Intervention] = []
        self._state: dict[str, CognitiveState] = {}

    def record_step(self, step: ReasoningStep) -> list[CognitiveSignal]:
        self._steps[step.agent_id].append(step)
        signals = self._analyze_step(step)
        self._signals.extend(signals)

        if signals:
            worst = max(signals, key=lambda s: self._state_severity(s.state))
            self._state[step.agent_id] = worst.state

            if self._config.auto_intervene:
                for signal in signals:
                    intervention = self._select_intervention(signal)
                    if intervention:
                        self._interventions.append(intervention)

        return signals

    def get_state(self, agent_id: str) -> CognitiveState:
        return self._state.get(agent_id, CognitiveState.FOCUSED)

    def get_steps(self, agent_id: str, last_n: int = 0) -> list[ReasoningStep]:
        steps = self._steps.get(agent_id, [])
        if last_n > 0:
            return steps[-last_n:]
        return list(steps)

    def get_interventions(self, agent_id: str | None = None) -> list[Intervention]:
        if agent_id:
            agent_signals = {s.signal_id for s in self._signals
                            if any(step.agent_id == agent_id for step in
                                   self._steps.get(agent_id, []))}
            return [i for i in self._interventions
                    if set(i.trigger_signals) & agent_signals]
        return list(self._interventions)

    def mark_intervention_applied(self, intervention_id: str, effective: bool = True) -> bool:
        for i, intervention in enumerate(self._interventions):
            if intervention.intervention_id == intervention_id:
                self._interventions[i] = Intervention(
                    intervention_id=intervention.intervention_id,
                    kind=intervention.kind,
                    trigger_state=intervention.trigger_state,
                    trigger_signals=intervention.trigger_signals,
                    description=intervention.description,
                    applied=True,
                    effective=effective,
                    applied_at=datetime.now(UTC),
                )
                return True
        return False

    def reset_state(self, agent_id: str) -> None:
        self._state[agent_id] = CognitiveState.FOCUSED

    def get_stats(self) -> MetacognitionStats:
        total_steps = sum(len(s) for s in self._steps.values())
        states_detected: dict[str, int] = defaultdict(int)
        for signal in self._signals:
            states_detected[signal.state.value] += 1

        effective = sum(1 for i in self._interventions if i.effective and i.applied)
        loop_count = states_detected.get(CognitiveState.LOOPING.value, 0)

        confidences = [s.confidence for s in self._signals] if self._signals else [0.0]

        return MetacognitionStats(
            total_steps=total_steps,
            total_signals=len(self._signals),
            total_interventions=len(self._interventions),
            interventions_effective=effective,
            states_detected=dict(states_detected),
            avg_confidence=sum(confidences) / len(confidences),
            loop_count=loop_count,
        )

    def _analyze_step(self, step: ReasoningStep) -> list[CognitiveSignal]:
        signals: list[CognitiveSignal] = []
        agent_steps = self._steps[step.agent_id]

        loop_signal = self._detect_loops(agent_steps)
        if loop_signal:
            signals.append(loop_signal)

        confidence_signal = self._check_confidence(step)
        if confidence_signal:
            signals.append(confidence_signal)

        progress_signal = self._check_progress(agent_steps)
        if progress_signal:
            signals.append(progress_signal)

        contradiction_signal = self._check_contradictions(agent_steps)
        if contradiction_signal:
            signals.append(contradiction_signal)

        complexity_signal = self._check_complexity(agent_steps)
        if complexity_signal:
            signals.append(complexity_signal)

        return signals

    def _detect_loops(self, steps: list[ReasoningStep]) -> CognitiveSignal | None:
        if len(steps) < self._config.repetition_threshold:
            return None

        recent = steps[-self._config.repetition_threshold:]
        hashes = [s.output_hash for s in recent if s.output_hash]

        if len(hashes) >= self._config.repetition_threshold:
            if len(set(hashes)) == 1:
                return CognitiveSignal(
                    source=SignalSource.REPETITION_DETECTOR,
                    state=CognitiveState.LOOPING,
                    confidence=0.9,
                    evidence=f"Same output hash repeated {len(hashes)} times",
                )

        actions = [s.action for s in recent]
        if len(set(actions)) == 1:
            return CognitiveSignal(
                source=SignalSource.REPETITION_DETECTOR,
                state=CognitiveState.LOOPING,
                confidence=0.7,
                evidence=f"Same action '{actions[0]}' repeated {len(actions)} times",
            )

        return None

    def _check_confidence(self, step: ReasoningStep) -> CognitiveSignal | None:
        if step.confidence < self._config.confidence_floor:
            return CognitiveSignal(
                source=SignalSource.CONFIDENCE_MONITOR,
                state=CognitiveState.CONFUSED,
                confidence=1.0 - step.confidence,
                evidence=f"Step confidence {step.confidence:.2f} below floor {self._config.confidence_floor}",
            )

        if step.confidence > self._config.confidence_ceiling:
            return CognitiveSignal(
                source=SignalSource.CONFIDENCE_MONITOR,
                state=CognitiveState.OVERCONFIDENT,
                confidence=0.6,
                evidence=f"Step confidence {step.confidence:.2f} above ceiling {self._config.confidence_ceiling}",
            )

        return None

    def _check_progress(self, steps: list[ReasoningStep]) -> CognitiveSignal | None:
        window = self._config.max_steps_without_progress
        if len(steps) < window:
            return None

        recent = steps[-window:]
        unique_actions = len(set(s.action for s in recent))
        unique_outputs = len(set(s.output_hash for s in recent if s.output_hash))

        if unique_actions <= 2 and unique_outputs <= 2:
            return CognitiveSignal(
                source=SignalSource.PROGRESS_TRACKER,
                state=CognitiveState.STUCK,
                confidence=0.7,
                evidence=f"Only {unique_actions} unique actions in last {window} steps",
            )

        return None

    def _check_contradictions(self, steps: list[ReasoningStep]) -> CognitiveSignal | None:
        window = min(len(steps), self._config.contradiction_window)
        if window < 4:
            return None

        recent = steps[-window:]
        action_pairs: dict[str, list[float]] = defaultdict(list)
        for s in recent:
            action_pairs[s.action].append(s.confidence)

        for action, confidences in action_pairs.items():
            if len(confidences) >= 2:
                spread = max(confidences) - min(confidences)
                if spread > 0.5:
                    return CognitiveSignal(
                        source=SignalSource.CONTRADICTION_CHECKER,
                        state=CognitiveState.UNCERTAIN,
                        confidence=spread,
                        evidence=f"Confidence spread {spread:.2f} for action '{action}'",
                    )

        return None

    def _check_complexity(self, steps: list[ReasoningStep]) -> CognitiveSignal | None:
        if len(steps) > self._config.complexity_budget:
            return CognitiveSignal(
                source=SignalSource.COMPLEXITY_MONITOR,
                state=CognitiveState.STUCK,
                confidence=0.8,
                evidence=f"Exceeded complexity budget: {len(steps)} > {self._config.complexity_budget}",
            )
        return None

    def _select_intervention(self, signal: CognitiveSignal) -> Intervention | None:
        mapping: dict[CognitiveState, InterventionKind] = {
            CognitiveState.LOOPING: InterventionKind.BACKTRACK,
            CognitiveState.CONFUSED: InterventionKind.SIMPLIFY,
            CognitiveState.STUCK: InterventionKind.REFRAME,
            CognitiveState.HALLUCINATING: InterventionKind.VERIFY,
            CognitiveState.OVERCONFIDENT: InterventionKind.VERIFY,
            CognitiveState.UNCERTAIN: InterventionKind.PAUSE,
        }

        kind = mapping.get(signal.state)
        if not kind:
            return None

        descriptions: dict[InterventionKind, str] = {
            InterventionKind.BACKTRACK: "Detected loop — backtrack to last divergence point",
            InterventionKind.SIMPLIFY: "Agent confused — simplify the problem decomposition",
            InterventionKind.REFRAME: "Agent stuck — reframe the approach from a different angle",
            InterventionKind.VERIFY: "Verify outputs against ground truth before proceeding",
            InterventionKind.PAUSE: "Uncertainty detected — pause and reassess assumptions",
            InterventionKind.ESCALATE: "Escalate to human for guidance",
            InterventionKind.ABORT: "Abort current reasoning chain",
        }

        return Intervention(
            kind=kind,
            trigger_state=signal.state,
            trigger_signals=(signal.signal_id,),
            description=descriptions.get(kind, ""),
        )

    def _state_severity(self, state: CognitiveState) -> int:
        severity = {
            CognitiveState.FOCUSED: 0,
            CognitiveState.UNCERTAIN: 1,
            CognitiveState.OVERCONFIDENT: 2,
            CognitiveState.CONFUSED: 3,
            CognitiveState.STUCK: 4,
            CognitiveState.LOOPING: 5,
            CognitiveState.HALLUCINATING: 6,
        }
        return severity.get(state, 0)
