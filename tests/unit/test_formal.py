"""Tests for formal methods: LTL model checking with counterexample generation."""

from __future__ import annotations

import pytest

from reins.formal import (
    AtomicProposition,
    CheckResult,
    Counterexample,
    FormalProperty,
    FormalStats,
    ModelCheckResult,
    ModelChecker,
    PropertyKind,
    StateSpace,
    TemporalFormula,
    TemporalOperator,
)


@pytest.fixture
def checker() -> ModelChecker:
    return ModelChecker()


@pytest.fixture
def simple_space(checker) -> StateSpace:
    """A simple 3-state machine: idle -> running -> done."""
    return checker.define_state_space(
        name="simple",
        states=["idle", "running", "done"],
        initial_state="idle",
        transitions=[
            ("idle", "start", "running"),
            ("running", "finish", "done"),
            ("done", "reset", "idle"),
        ],
        propositions={
            "active": ["running"],
            "completed": ["done"],
            "safe": ["idle", "running", "done"],
        },
    )


@pytest.fixture
def deadlock_space(checker) -> StateSpace:
    """A space with a deadlock state."""
    return checker.define_state_space(
        name="deadlock",
        states=["s0", "s1", "s2_dead"],
        initial_state="s0",
        transitions=[
            ("s0", "go", "s1"),
            ("s1", "trap", "s2_dead"),
        ],
        propositions={"alive": ["s0", "s1"]},
    )


def test_define_proposition(checker):
    prop = checker.define_proposition("safe", predicate="state != error")
    assert prop.name == "safe"


def test_define_formula(checker):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    assert f.operator == TemporalOperator.ALWAYS


def test_define_property(checker):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("safety", PropertyKind.SAFETY, f.formula_id)
    assert checker.get_property(p.property_id) is not None


def test_get_property_not_found(checker):
    assert checker.get_property("nonexistent") is None


def test_define_state_space(checker, simple_space):
    assert checker.get_state_space(simple_space.space_id) is not None
    assert len(simple_space.states) == 3


def test_get_state_space_not_found(checker):
    assert checker.get_state_space("nonexistent") is None


def test_check_always_satisfied(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("all_safe", PropertyKind.SAFETY, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.SATISFIED


def test_check_always_violated(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="active")
    p = checker.define_property("always_active", PropertyKind.INVARIANCE, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.VIOLATED
    assert result.counterexample is not None


def test_check_eventually_satisfied(checker, simple_space):
    f = checker.define_formula(TemporalOperator.EVENTUALLY, atom="completed")
    p = checker.define_property("reaches_done", PropertyKind.LIVENESS, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.SATISFIED


def test_check_eventually_violated(checker, simple_space):
    f = checker.define_formula(TemporalOperator.EVENTUALLY, atom="nonexistent_prop")
    p = checker.define_property("reaches_nowhere", PropertyKind.REACHABILITY, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.VIOLATED


def test_check_not_satisfied(checker, simple_space):
    f = checker.define_formula(TemporalOperator.NOT, atom="nonexistent_prop")
    p = checker.define_property("no_bad", PropertyKind.SAFETY, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.SATISFIED


def test_check_not_violated(checker, simple_space):
    f = checker.define_formula(TemporalOperator.NOT, atom="safe")
    p = checker.define_property("not_safe", PropertyKind.SAFETY, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.result == CheckResult.VIOLATED


def test_counterexample_has_trace(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="active")
    p = checker.define_property("always_active", PropertyKind.INVARIANCE, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert len(result.counterexample.trace) > 0


def test_counterexample_starts_at_initial(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="active")
    p = checker.define_property("always_active", PropertyKind.INVARIANCE, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.counterexample.trace[0] == "idle"


def test_check_safety_satisfied(checker, simple_space):
    result = checker.check_safety(simple_space.space_id, bad_states=["error", "crash"])
    assert result.result == CheckResult.SATISFIED


def test_check_safety_violated(checker, simple_space):
    result = checker.check_safety(simple_space.space_id, bad_states=["done"])
    assert result.result == CheckResult.VIOLATED
    assert "done" in result.counterexample.explanation


def test_check_liveness_satisfied(checker, simple_space):
    result = checker.check_liveness(simple_space.space_id, target_state="done")
    assert result.result == CheckResult.SATISFIED


def test_check_liveness_violated_unreachable(checker):
    space = checker.define_state_space(
        name="no_exit",
        states=["a", "b", "target"],
        initial_state="a",
        transitions=[("a", "go", "b"), ("b", "back", "a")],
        propositions={},
    )
    result = checker.check_liveness(space.space_id, target_state="target")
    assert result.result == CheckResult.VIOLATED


def test_check_deadlock_freedom_satisfied(checker, simple_space):
    result = checker.check_deadlock_freedom(simple_space.space_id)
    assert result.result == CheckResult.SATISFIED


def test_check_deadlock_freedom_violated(checker, deadlock_space):
    result = checker.check_deadlock_freedom(deadlock_space.space_id)
    assert result.result == CheckResult.VIOLATED
    assert "s2_dead" in result.counterexample.trace


def test_check_all(checker, simple_space):
    f1 = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    f2 = checker.define_formula(TemporalOperator.EVENTUALLY, atom="completed")
    checker.define_property("p1", PropertyKind.SAFETY, f1.formula_id)
    checker.define_property("p2", PropertyKind.LIVENESS, f2.formula_id)
    results = checker.check_all(simple_space.space_id)
    assert len(results) == 2
    assert all(r.result == CheckResult.SATISFIED for r in results)


def test_check_nonexistent_property(checker, simple_space):
    result = checker.check_property("nonexistent", simple_space.space_id)
    assert result.result == CheckResult.UNKNOWN


def test_check_nonexistent_space(checker):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("p", PropertyKind.SAFETY, f.formula_id)
    result = checker.check_property(p.property_id, "nonexistent")
    assert result.result == CheckResult.UNKNOWN


def test_states_explored_counted(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("p", PropertyKind.SAFETY, f.formula_id)
    result = checker.check_property(p.property_id, simple_space.space_id)
    assert result.states_explored == 3


def test_get_results(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("p", PropertyKind.SAFETY, f.formula_id)
    checker.check_property(p.property_id, simple_space.space_id)
    assert len(checker.get_results()) == 1


def test_get_results_by_property(checker, simple_space):
    f1 = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    f2 = checker.define_formula(TemporalOperator.EVENTUALLY, atom="completed")
    p1 = checker.define_property("p1", PropertyKind.SAFETY, f1.formula_id)
    p2 = checker.define_property("p2", PropertyKind.LIVENESS, f2.formula_id)
    checker.check_property(p1.property_id, simple_space.space_id)
    checker.check_property(p2.property_id, simple_space.space_id)
    assert len(checker.get_results(property_id=p1.property_id)) == 1


def test_stats_empty():
    mc = ModelChecker()
    stats = mc.get_stats()
    assert stats.total_properties == 0
    assert stats.total_checks == 0


def test_stats_with_data(checker, simple_space):
    f = checker.define_formula(TemporalOperator.ALWAYS, atom="safe")
    p = checker.define_property("p", PropertyKind.SAFETY, f.formula_id)
    checker.check_property(p.property_id, simple_space.space_id)
    stats = checker.get_stats()
    assert stats.total_properties == 1
    assert stats.total_spaces == 1
    assert stats.total_checks == 1
    assert stats.satisfied == 1
    assert stats.avg_states_explored == 3.0


def test_large_state_space(checker):
    states = [f"s{i}" for i in range(50)]
    transitions = [(f"s{i}", "next", f"s{i+1}") for i in range(49)]
    transitions.append(("s49", "loop", "s0"))
    space = checker.define_state_space(
        name="large", states=states, initial_state="s0",
        transitions=transitions,
        propositions={"start": ["s0"], "end": ["s49"]},
    )
    result = checker.check_safety(space.space_id, bad_states=["nonexistent"])
    assert result.result == CheckResult.SATISFIED
    assert result.states_explored == 50
