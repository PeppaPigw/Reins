"""Tests for agent metacognition engine."""

from __future__ import annotations

import pytest

from reins.metacognition import (
    CognitiveSignal,
    CognitiveState,
    Intervention,
    InterventionKind,
    MetacognitionConfig,
    MetacognitionEngine,
    MetacognitionStats,
    ReasoningStep,
    SignalSource,
)


@pytest.fixture
def engine() -> MetacognitionEngine:
    return MetacognitionEngine(config=MetacognitionConfig(
        repetition_threshold=3,
        confidence_floor=0.2,
        confidence_ceiling=0.95,
        max_steps_without_progress=5,
        contradiction_window=10,
        complexity_budget=50,
        auto_intervene=True,
    ))


def _step(agent_id="agent-1", action="think", output_hash="", confidence=0.5,
          tokens_used=100):
    return ReasoningStep(
        agent_id=agent_id,
        action=action,
        output_hash=output_hash,
        confidence=confidence,
        tokens_used=tokens_used,
    )


def test_initial_state_is_focused(engine):
    assert engine.get_state("agent-1") == CognitiveState.FOCUSED


def test_normal_step_no_signals(engine):
    signals = engine.record_step(_step(action="analyze", output_hash="abc"))
    assert len(signals) == 0
    assert engine.get_state("agent-1") == CognitiveState.FOCUSED


def test_detect_loop_same_output(engine):
    for i in range(3):
        signals = engine.record_step(_step(output_hash="same_hash"))
    assert len(signals) > 0
    assert any(s.state == CognitiveState.LOOPING for s in signals)


def test_detect_loop_same_action(engine):
    for i in range(3):
        signals = engine.record_step(_step(action="retry"))
    assert any(s.state == CognitiveState.LOOPING for s in signals)


def test_low_confidence_triggers_confused(engine):
    signals = engine.record_step(_step(confidence=0.1))
    assert any(s.state == CognitiveState.CONFUSED for s in signals)


def test_high_confidence_triggers_overconfident(engine):
    signals = engine.record_step(_step(confidence=0.99))
    assert any(s.state == CognitiveState.OVERCONFIDENT for s in signals)


def test_normal_confidence_no_signal(engine):
    signals = engine.record_step(_step(confidence=0.6))
    confidence_signals = [s for s in signals if s.source == SignalSource.CONFIDENCE_MONITOR]
    assert len(confidence_signals) == 0


def test_stuck_detection(engine):
    for i in range(5):
        engine.record_step(_step(action="think", output_hash="same"))
    signals = engine.record_step(_step(action="think", output_hash="same"))
    stuck_signals = [s for s in signals if s.state == CognitiveState.STUCK]
    assert len(stuck_signals) > 0


def test_complexity_budget_exceeded(engine):
    eng = MetacognitionEngine(config=MetacognitionConfig(complexity_budget=5))
    for i in range(6):
        signals = eng.record_step(_step(action=f"step-{i}", output_hash=f"h{i}"))
    assert any(s.state == CognitiveState.STUCK for s in signals)


def test_contradiction_detection(engine):
    for i in range(5):
        conf = 0.9 if i % 2 == 0 else 0.2
        signals = engine.record_step(_step(action="decide", confidence=conf))
    uncertain_signals = [s for s in signals if s.state == CognitiveState.UNCERTAIN]
    assert len(uncertain_signals) > 0


def test_auto_intervention_on_loop(engine):
    for i in range(3):
        engine.record_step(_step(output_hash="loop"))
    interventions = engine.get_interventions("agent-1")
    assert len(interventions) > 0
    assert any(i.kind == InterventionKind.BACKTRACK for i in interventions)


def test_auto_intervention_on_confusion(engine):
    engine.record_step(_step(confidence=0.05))
    interventions = engine.get_interventions("agent-1")
    assert any(i.kind == InterventionKind.SIMPLIFY for i in interventions)


def test_auto_intervention_disabled():
    eng = MetacognitionEngine(config=MetacognitionConfig(auto_intervene=False))
    for i in range(3):
        eng.record_step(_step(output_hash="loop"))
    interventions = eng.get_interventions("agent-1")
    assert len(interventions) == 0


def test_mark_intervention_applied(engine):
    engine.record_step(_step(confidence=0.05))
    interventions = engine.get_interventions("agent-1")
    assert len(interventions) > 0

    result = engine.mark_intervention_applied(interventions[0].intervention_id, effective=True)
    assert result


def test_mark_intervention_nonexistent(engine):
    assert not engine.mark_intervention_applied("nonexistent")


def test_reset_state(engine):
    for i in range(3):
        engine.record_step(_step(output_hash="loop"))
    assert engine.get_state("agent-1") != CognitiveState.FOCUSED

    engine.reset_state("agent-1")
    assert engine.get_state("agent-1") == CognitiveState.FOCUSED


def test_get_steps(engine):
    engine.record_step(_step(action="a"))
    engine.record_step(_step(action="b"))
    engine.record_step(_step(action="c"))

    all_steps = engine.get_steps("agent-1")
    assert len(all_steps) == 3

    last_two = engine.get_steps("agent-1", last_n=2)
    assert len(last_two) == 2
    assert last_two[0].action == "b"


def test_multiple_agents_independent(engine):
    engine.record_step(_step(agent_id="a", confidence=0.05))
    engine.record_step(_step(agent_id="b", action="normal", confidence=0.6))

    assert engine.get_state("a") == CognitiveState.CONFUSED
    assert engine.get_state("b") == CognitiveState.FOCUSED


def test_stats_empty():
    eng = MetacognitionEngine()
    stats = eng.get_stats()
    assert stats.total_steps == 0
    assert stats.total_signals == 0


def test_stats_with_data(engine):
    for i in range(3):
        engine.record_step(_step(output_hash="loop"))
    engine.record_step(_step(confidence=0.05))

    stats = engine.get_stats()
    assert stats.total_steps == 4
    assert stats.total_signals > 0
    assert stats.total_interventions > 0
    assert CognitiveState.LOOPING.value in stats.states_detected


def test_stats_effective_interventions(engine):
    engine.record_step(_step(confidence=0.05))
    interventions = engine.get_interventions("agent-1")
    engine.mark_intervention_applied(interventions[0].intervention_id, effective=True)

    stats = engine.get_stats()
    assert stats.interventions_effective == 1


def test_loop_count_in_stats(engine):
    for i in range(3):
        engine.record_step(_step(output_hash="loop"))

    stats = engine.get_stats()
    assert stats.loop_count >= 1


def test_worst_state_wins(engine):
    engine.record_step(_step(confidence=0.05))
    for i in range(3):
        engine.record_step(_step(output_hash="loop"))
    assert engine.get_state("agent-1") == CognitiveState.LOOPING
