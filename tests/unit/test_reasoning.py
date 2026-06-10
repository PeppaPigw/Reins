"""Tests for reasoning engine with logical inference and consistency."""

from __future__ import annotations

import pytest

from reins.reasoning import (
    Argument,
    ArgumentStrength,
    Contradiction,
    InferenceRule,
    InferenceStep,
    LogicKind,
    Proposition,
    PropositionStatus,
    ReasoningEngine,
    ReasoningStats,
)


@pytest.fixture
def engine() -> ReasoningEngine:
    return ReasoningEngine()


def test_assert_proposition(engine):
    prop = engine.assert_proposition("the sky is blue", confidence=0.9)
    assert prop.statement == "the sky is blue"
    assert prop.confidence == 0.9
    assert prop.status == PropositionStatus.ASSUMED


def test_get_proposition(engine):
    prop = engine.assert_proposition("test")
    assert engine.get_proposition(prop.prop_id) is not None
    assert engine.get_proposition("nonexistent") is None


def test_retract_proposition(engine):
    prop = engine.assert_proposition("wrong claim")
    retracted = engine.retract_proposition(prop.prop_id)
    assert retracted.status == PropositionStatus.RETRACTED


def test_retract_not_found(engine):
    assert engine.retract_proposition("nonexistent") is None


def test_get_active_propositions(engine):
    engine.assert_proposition("active")
    p2 = engine.assert_proposition("to retract")
    engine.retract_proposition(p2.prop_id)
    active = engine.get_active_propositions()
    assert len(active) == 1
    assert active[0].statement == "active"


def test_register_rule(engine):
    rule = engine.register_rule("modus ponens", ["P", "P implies Q"], "Q")
    assert rule.name == "modus ponens"
    assert rule.kind == LogicKind.DEDUCTIVE


def test_get_rule(engine):
    rule = engine.register_rule("test", ["A"], "B")
    assert engine.get_rule(rule.rule_id) is not None
    assert engine.get_rule("nonexistent") is None


def test_apply_rule(engine):
    p1 = engine.assert_proposition("all humans are mortal")
    p2 = engine.assert_proposition("socrates is human")
    rule = engine.register_rule(
        "syllogism", ["all humans are mortal", "socrates is human"],
        "socrates is mortal",
    )
    conclusion = engine.apply_rule(rule.rule_id, [p1.prop_id, p2.prop_id])
    assert conclusion is not None
    assert conclusion.statement == "socrates is mortal"
    assert conclusion.status == PropositionStatus.DERIVED


def test_apply_rule_confidence_propagation(engine):
    p1 = engine.assert_proposition("premise 1", confidence=0.8)
    p2 = engine.assert_proposition("premise 2", confidence=0.9)
    rule = engine.register_rule("r", ["premise 1", "premise 2"], "conclusion", strength=0.9)
    conclusion = engine.apply_rule(rule.rule_id, [p1.prop_id, p2.prop_id])
    assert conclusion.confidence == pytest.approx(0.8 * 0.9)


def test_apply_rule_not_found(engine):
    assert engine.apply_rule("nonexistent", []) is None


def test_apply_rule_retracted_premise(engine):
    p1 = engine.assert_proposition("premise")
    engine.retract_proposition(p1.prop_id)
    rule = engine.register_rule("r", ["premise"], "conclusion")
    assert engine.apply_rule(rule.rule_id, [p1.prop_id]) is None


def test_apply_rule_missing_premise(engine):
    rule = engine.register_rule("r", ["A"], "B")
    assert engine.apply_rule(rule.rule_id, ["nonexistent"]) is None


def test_build_argument_strong(engine):
    p1 = engine.assert_proposition("evidence 1", confidence=0.9)
    p2 = engine.assert_proposition("evidence 2", confidence=0.85)
    arg = engine.build_argument("conclusion", [p1.prop_id, p2.prop_id])
    assert arg.strength == ArgumentStrength.STRONG
    assert arg.confidence > 0.8


def test_build_argument_weak(engine):
    p1 = engine.assert_proposition("weak evidence", confidence=0.3)
    arg = engine.build_argument("claim", [p1.prop_id])
    assert arg.strength == ArgumentStrength.WEAK


def test_build_argument_no_premises(engine):
    arg = engine.build_argument("baseless claim", ["nonexistent"])
    assert arg.strength == ArgumentStrength.FALLACIOUS
    assert arg.confidence == 0.0


def test_get_argument(engine):
    p = engine.assert_proposition("evidence")
    arg = engine.build_argument("claim", [p.prop_id])
    assert engine.get_argument(arg.argument_id) is not None
    assert engine.get_argument("nonexistent") is None


def test_contradiction_detection(engine):
    engine.assert_proposition("the door is open")
    engine.assert_proposition("not the door is open")
    contradictions = engine.get_contradictions()
    assert len(contradictions) == 1


def test_contradiction_with_negation_markers(engine):
    engine.assert_proposition("cats can fly")
    engine.assert_proposition("cannot cats can fly")
    contradictions = engine.get_contradictions()
    assert len(contradictions) == 1


def test_no_false_contradiction(engine):
    engine.assert_proposition("the sky is blue")
    engine.assert_proposition("the grass is green")
    contradictions = engine.get_contradictions()
    assert len(contradictions) == 0


def test_resolve_contradiction(engine):
    p1 = engine.assert_proposition("X is true")
    engine.assert_proposition("not X is true")
    contradictions = engine.get_contradictions(unresolved_only=True)
    assert len(contradictions) == 1
    resolved = engine.resolve_contradiction(contradictions[0].contradiction_id, p1.prop_id)
    assert resolved.resolved is True
    unresolved = engine.get_contradictions(unresolved_only=True)
    assert len(unresolved) == 0


def test_resolve_contradiction_not_found(engine):
    assert engine.resolve_contradiction("nonexistent", "x") is None


def test_get_inference_chain(engine):
    p1 = engine.assert_proposition("A")
    rule = engine.register_rule("r1", ["A"], "B")
    conclusion = engine.apply_rule(rule.rule_id, [p1.prop_id])
    chain = engine.get_inference_chain(conclusion.prop_id)
    assert len(chain) == 1
    assert chain[0].conclusion_id == conclusion.prop_id


def test_inference_chain_multi_step(engine):
    p1 = engine.assert_proposition("base fact")
    r1 = engine.register_rule("step1", ["base fact"], "intermediate")
    intermediate = engine.apply_rule(r1.rule_id, [p1.prop_id])
    r2 = engine.register_rule("step2", ["intermediate"], "final")
    final = engine.apply_rule(r2.rule_id, [intermediate.prop_id])
    chain = engine.get_inference_chain(final.prop_id)
    assert len(chain) == 2


def test_forward_chain(engine):
    engine.assert_proposition("it is raining")
    engine.register_rule("wet rule", ["it is raining"], "the ground is wet")
    derived = engine.forward_chain()
    assert len(derived) >= 1
    assert any(p.statement == "the ground is wet" for p in derived)


def test_forward_chain_no_match(engine):
    engine.assert_proposition("unrelated fact")
    engine.register_rule("rule", ["missing premise"], "conclusion")
    derived = engine.forward_chain()
    assert len(derived) == 0


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_propositions == 0
    assert stats.total_rules == 0


def test_stats_populated(engine):
    p1 = engine.assert_proposition("fact", confidence=0.8)
    p2 = engine.assert_proposition("another fact", confidence=0.9)
    rule = engine.register_rule("r", ["fact"], "derived", kind=LogicKind.INDUCTIVE)
    engine.apply_rule(rule.rule_id, [p1.prop_id])
    engine.build_argument("claim", [p1.prop_id, p2.prop_id])
    stats = engine.get_stats()
    assert stats.total_propositions == 3
    assert stats.total_rules == 1
    assert stats.total_inferences == 1
    assert stats.total_arguments == 1
    assert "inductive" in stats.by_logic_kind
