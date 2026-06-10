"""Tests for contract testing engine."""

from __future__ import annotations

import pytest

from reins.contracts import (
    ContractCheckResult,
    ContractClause,
    ContractDefinition,
    ContractEngine,
    ContractKind,
    ContractStats,
    ContractViolation,
    EnforcementMode,
    ViolationSeverity,
)


@pytest.fixture
def engine() -> ContractEngine:
    return ContractEngine()


def _clause(name="check_input", kind=ContractKind.PRECONDITION,
            severity=ViolationSeverity.ERROR, clause_id=None):
    kwargs = {"name": name, "kind": kind, "severity": severity}
    if clause_id:
        kwargs["clause_id"] = clause_id
    return ContractClause(**kwargs)


def _contract(name="test_contract", clauses=(), enforcement=EnforcementMode.ENFORCE,
              contract_id=None):
    kwargs = {"name": name, "clauses": clauses, "enforcement": enforcement}
    if contract_id:
        kwargs["contract_id"] = contract_id
    return ContractDefinition(**kwargs)


def test_register_and_check_passing(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: True)

    result = engine.check_contract("ct1")
    assert result.passed
    assert len(result.violations) == 0
    assert result.clauses_checked == 1
    assert result.clauses_passed == 1


def test_check_failing_clause(engine):
    clause = _clause(clause_id="c1", name="must_have_token")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: ctx.get("token") is not None)

    result = engine.check_contract("ct1", context={})
    assert not result.passed
    assert len(result.violations) == 1
    assert result.violations[0].clause_name == "must_have_token"


def test_check_nonexistent_contract(engine):
    result = engine.check_contract("nonexistent")
    assert not result.passed
    assert "not found" in result.violations[0].message


def test_checker_exception_becomes_violation(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: 1 / 0)

    result = engine.check_contract("ct1")
    assert not result.passed
    assert "Checker raised" in result.violations[0].message


def test_multiple_clauses_partial_failure(engine):
    c1 = _clause(clause_id="c1", name="first")
    c2 = _clause(clause_id="c2", name="second")
    c3 = _clause(clause_id="c3", name="third")
    contract = _contract(clauses=(c1, c2, c3), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: True)
    engine.register_checker("c2", lambda ctx: False)
    engine.register_checker("c3", lambda ctx: True)

    result = engine.check_contract("ct1")
    assert not result.passed
    assert result.clauses_checked == 3
    assert result.clauses_passed == 2
    assert len(result.violations) == 1


def test_check_preconditions_only(engine):
    pre = _clause(clause_id="pre1", kind=ContractKind.PRECONDITION)
    post = _clause(clause_id="post1", kind=ContractKind.POSTCONDITION)
    contract = _contract(clauses=(pre, post), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("pre1", lambda ctx: True)
    engine.register_checker("post1", lambda ctx: False)

    result = engine.check_preconditions("ct1")
    assert result.passed


def test_check_postconditions_only(engine):
    pre = _clause(clause_id="pre1", kind=ContractKind.PRECONDITION)
    post = _clause(clause_id="post1", kind=ContractKind.POSTCONDITION)
    contract = _contract(clauses=(pre, post), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("pre1", lambda ctx: False)
    engine.register_checker("post1", lambda ctx: True)

    result = engine.check_postconditions("ct1")
    assert result.passed


def test_check_invariants_only(engine):
    inv = _clause(clause_id="inv1", kind=ContractKind.INVARIANT)
    pre = _clause(clause_id="pre1", kind=ContractKind.PRECONDITION)
    contract = _contract(clauses=(inv, pre), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("inv1", lambda ctx: False)
    engine.register_checker("pre1", lambda ctx: True)

    result = engine.check_invariants("ct1")
    assert not result.passed


def test_should_abort_with_abort_mode(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1", enforcement=EnforcementMode.ABORT)
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)

    result = engine.check_contract("ct1")
    assert engine.should_abort(result)


def test_should_not_abort_with_monitor_mode(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1", enforcement=EnforcementMode.MONITOR)
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)

    result = engine.check_contract("ct1")
    assert not engine.should_abort(result)


def test_should_abort_enforce_only_on_critical(engine):
    clause = _clause(clause_id="c1", severity=ViolationSeverity.ERROR)
    contract = _contract(clauses=(clause,), contract_id="ct1", enforcement=EnforcementMode.ENFORCE)
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)

    result = engine.check_contract("ct1")
    assert not engine.should_abort(result)

    crit_clause = _clause(clause_id="c2", severity=ViolationSeverity.CRITICAL)
    contract2 = _contract(clauses=(crit_clause,), contract_id="ct2", enforcement=EnforcementMode.ENFORCE)
    engine.register_contract(contract2)
    engine.register_checker("c2", lambda ctx: False)

    result2 = engine.check_contract("ct2")
    assert engine.should_abort(result2)


def test_get_violations_all(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)
    engine.check_contract("ct1")

    violations = engine.get_violations()
    assert len(violations) == 1


def test_get_violations_by_severity(engine):
    c1 = _clause(clause_id="c1", severity=ViolationSeverity.WARNING)
    c2 = _clause(clause_id="c2", severity=ViolationSeverity.CRITICAL)
    contract = _contract(clauses=(c1, c2), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)
    engine.register_checker("c2", lambda ctx: False)
    engine.check_contract("ct1")

    warnings = engine.get_violations(severity=ViolationSeverity.WARNING)
    assert len(warnings) == 1
    criticals = engine.get_violations(severity=ViolationSeverity.CRITICAL)
    assert len(criticals) == 1


def test_context_passed_to_checker(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: ctx.get("value") == 42)

    assert engine.check_contract("ct1", {"value": 42}).passed
    assert not engine.check_contract("ct1", {"value": 0}).passed


def test_duration_tracked(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: True)

    result = engine.check_contract("ct1")
    assert result.duration_ms >= 0


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_contracts == 0
    assert stats.total_checks == 0
    assert stats.pass_rate == 0.0


def test_stats_with_data(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: True)

    engine.check_contract("ct1")
    engine.check_contract("ct1")

    stats = engine.get_stats()
    assert stats.total_contracts == 1
    assert stats.total_checks == 2
    assert stats.pass_rate == 1.0
    assert stats.total_violations == 0


def test_stats_violations_by_kind(engine):
    pre = _clause(clause_id="c1", kind=ContractKind.PRECONDITION)
    inv = _clause(clause_id="c2", kind=ContractKind.INVARIANT)
    contract = _contract(clauses=(pre, inv), contract_id="ct1")
    engine.register_contract(contract)
    engine.register_checker("c1", lambda ctx: False)
    engine.register_checker("c2", lambda ctx: False)
    engine.check_contract("ct1")

    stats = engine.get_stats()
    assert stats.violations_by_kind["precondition"] == 1
    assert stats.violations_by_kind["invariant"] == 1


def test_no_checker_registered_skips_clause(engine):
    clause = _clause(clause_id="c1")
    contract = _contract(clauses=(clause,), contract_id="ct1")
    engine.register_contract(contract)

    result = engine.check_contract("ct1")
    assert result.passed
    assert result.clauses_checked == 0
