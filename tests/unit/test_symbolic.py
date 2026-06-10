"""Tests for symbolic reasoning with first-order logic."""

from __future__ import annotations

import pytest

from reins.symbolic import (
    InferenceRule,
    ProofResult,
    ProofStatus,
    SymbolicReasoner,
    SymbolicStats,
)


@pytest.fixture
def reasoner() -> SymbolicReasoner:
    return SymbolicReasoner()


@pytest.fixture
def family_kb(reasoner) -> SymbolicReasoner:
    reasoner.assert_fact("parent(tom, bob)")
    reasoner.assert_fact("parent(tom, liz)")
    reasoner.assert_fact("parent(bob, ann)")
    reasoner.assert_fact("parent(bob, pat)")
    reasoner.assert_fact("male(tom)")
    reasoner.assert_fact("male(bob)")
    reasoner.assert_fact("female(liz)")
    reasoner.assert_fact("female(ann)")
    reasoner.add_rule(["parent(X, Y)", "male(X)"], "father(X, Y)")
    reasoner.add_rule(["parent(X, Y)", "parent(Y, Z)"], "grandparent(X, Z)")
    return reasoner


def test_assert_fact(reasoner):
    reasoner.assert_fact("human(socrates)")
    assert "human(socrates)" in reasoner.get_facts()


def test_retract_fact(reasoner):
    reasoner.assert_fact("temp(x)")
    assert reasoner.retract_fact("temp(x)")
    assert "temp(x)" not in reasoner.get_facts()


def test_retract_nonexistent(reasoner):
    assert not reasoner.retract_fact("nonexistent")


def test_add_rule(reasoner):
    reasoner.add_rule(["human(X)"], "mortal(X)")
    assert len(reasoner.get_rules()) == 1


def test_prove_direct_fact(reasoner):
    reasoner.assert_fact("human(socrates)")
    result = reasoner.prove("human(socrates)")
    assert result.status == ProofStatus.PROVED


def test_prove_unknown(reasoner):
    result = reasoner.prove("flying(pig)")
    assert result.status == ProofStatus.UNKNOWN


def test_prove_via_rule(reasoner):
    reasoner.assert_fact("human(socrates)")
    reasoner.add_rule(["human(X)"], "mortal(X)")
    result = reasoner.prove("mortal(socrates)")
    assert result.status == ProofStatus.PROVED


def test_prove_chain(family_kb):
    result = family_kb.prove("father(tom, bob)")
    assert result.status == ProofStatus.PROVED


def test_prove_grandparent(family_kb):
    result = family_kb.prove("grandparent(tom, ann)")
    assert result.status == ProofStatus.PROVED


def test_prove_has_steps(family_kb):
    result = family_kb.prove("father(tom, bob)")
    assert len(result.steps) > 0


def test_forward_chain(reasoner):
    reasoner.assert_fact("human(socrates)")
    reasoner.add_rule(["human(socrates)"], "mortal(socrates)")
    derived = reasoner.forward_chain()
    assert "mortal(socrates)" in derived
    assert "mortal(socrates)" in reasoner.get_facts()


def test_forward_chain_transitive(reasoner):
    reasoner.assert_fact("a(x)")
    reasoner.add_rule(["a(x)"], "b(x)")
    reasoner.add_rule(["b(x)"], "c(x)")
    derived = reasoner.forward_chain()
    assert "b(x)" in derived
    assert "c(x)" in derived


def test_forward_chain_no_new_facts(reasoner):
    reasoner.assert_fact("a(x)")
    derived = reasoner.forward_chain()
    assert len(derived) == 0


def test_unify_identical(reasoner):
    result = reasoner.unify("parent(tom, bob)", "parent(tom, bob)")
    assert result is not None


def test_unify_variable(reasoner):
    result = reasoner.unify("parent(X, bob)", "parent(tom, bob)")
    assert result is not None
    assert result.get("X") == "tom"


def test_unify_two_variables(reasoner):
    result = reasoner.unify("parent(X, Y)", "parent(tom, bob)")
    assert result is not None
    assert result.get("X") == "tom"
    assert result.get("Y") == "bob"


def test_unify_fails(reasoner):
    result = reasoner.unify("parent(tom, bob)", "parent(tom, liz)")
    assert result is None


def test_unify_different_predicates(reasoner):
    result = reasoner.unify("parent(tom, bob)", "child(tom, bob)")
    assert result is None


def test_query_with_variable(family_kb):
    results = family_kb.query_with_variable("parent(tom, X)", "X")
    assert "bob" in results
    assert "liz" in results


def test_query_with_variable_no_match(family_kb):
    results = family_kb.query_with_variable("parent(nobody, X)", "X")
    assert len(results) == 0


def test_is_consistent(reasoner):
    reasoner.assert_fact("alive(cat)")
    assert reasoner.is_consistent()


def test_is_inconsistent(reasoner):
    reasoner.assert_fact("alive(cat)")
    reasoner.assert_fact("not_alive(cat)")
    assert not reasoner.is_consistent()


def test_prove_all(reasoner):
    reasoner.assert_fact("a(x)")
    reasoner.assert_fact("b(y)")
    results = reasoner.prove_all(["a(x)", "b(y)", "c(z)"])
    assert results[0].status == ProofStatus.PROVED
    assert results[1].status == ProofStatus.PROVED
    assert results[2].status == ProofStatus.UNKNOWN


def test_stats_empty():
    r = SymbolicReasoner()
    stats = r.get_stats()
    assert stats.total_facts == 0
    assert stats.total_rules == 0


def test_stats_with_data(family_kb):
    family_kb.prove("father(tom, bob)")
    family_kb.prove("flying(pig)")
    stats = family_kb.get_stats()
    assert stats.total_facts == 8
    assert stats.total_rules == 2
    assert stats.total_queries == 2
    assert stats.proofs_found == 1
    assert ProofStatus.PROVED.value in stats.by_status
