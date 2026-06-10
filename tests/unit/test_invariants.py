"""Tests for runtime invariant verification engine."""

from __future__ import annotations

import pytest

from reins.invariants import (
    CheckResult,
    InvariantCheck,
    InvariantChecker,
    InvariantKind,
    InvariantSpec,
    InvariantStats,
    SafetyProof,
    Violation,
    ViolationSeverity,
)


@pytest.fixture
def checker() -> InvariantChecker:
    return InvariantChecker()


def test_define_invariant(checker):
    spec = checker.define_invariant("no_negative_balance", InvariantKind.SAFETY,
                                    description="Balance must never go negative")
    assert spec.name == "no_negative_balance"
    assert spec.kind == InvariantKind.SAFETY
    assert spec.enabled is True


def test_define_with_checker(checker):
    spec = checker.define_invariant(
        "positive", InvariantKind.BOUNDEDNESS,
        checker=lambda s: s.get("value", 0) > 0,
    )
    result = checker.check(spec.spec_id, {"value": 5})
    assert result.result == CheckResult.SATISFIED


def test_get_spec(checker):
    spec = checker.define_invariant("test", InvariantKind.SAFETY)
    assert checker.get_spec(spec.spec_id) is not None
    assert checker.get_spec("nonexistent") is None


def test_disable_enable_invariant(checker):
    spec = checker.define_invariant("test", InvariantKind.SAFETY,
                                    checker=lambda s: True)
    disabled = checker.disable_invariant(spec.spec_id)
    assert disabled.enabled is False
    result = checker.check(spec.spec_id, {})
    assert result.result == CheckResult.SKIPPED

    enabled = checker.enable_invariant(spec.spec_id)
    assert enabled.enabled is True
    result = checker.check(spec.spec_id, {})
    assert result.result == CheckResult.SATISFIED


def test_disable_nonexistent(checker):
    assert checker.disable_invariant("nope") is None
    assert checker.enable_invariant("nope") is None


def test_check_spec_not_found(checker):
    result = checker.check("missing", {"x": 1})
    assert result.result == CheckResult.SKIPPED
    assert "not found" in result.message


def test_check_no_checker_registered(checker):
    spec = checker.define_invariant("bare", InvariantKind.LIVENESS)
    result = checker.check(spec.spec_id, {"x": 1})
    assert result.result == CheckResult.UNKNOWN
    assert "No checker" in result.message


def test_check_satisfied(checker):
    spec = checker.define_invariant(
        "bounded", InvariantKind.BOUNDEDNESS,
        checker=lambda s: s["count"] < 100,
    )
    result = checker.check(spec.spec_id, {"count": 50})
    assert result.result == CheckResult.SATISFIED


def test_check_violated(checker):
    spec = checker.define_invariant(
        "bounded", InvariantKind.BOUNDEDNESS,
        severity=ViolationSeverity.CRITICAL,
        checker=lambda s: s["count"] < 100,
    )
    result = checker.check(spec.spec_id, {"count": 200})
    assert result.result == CheckResult.VIOLATED
    violations = checker.get_violations(spec_id=spec.spec_id)
    assert len(violations) == 1
    assert violations[0].severity == ViolationSeverity.CRITICAL


def test_check_exception_in_checker(checker):
    spec = checker.define_invariant(
        "bad", InvariantKind.SAFETY,
        checker=lambda s: s["missing_key"],
    )
    result = checker.check(spec.spec_id, {})
    assert result.result == CheckResult.UNKNOWN
    assert "Checker error" in result.message


def test_check_all(checker):
    checker.define_invariant("a", InvariantKind.SAFETY, checker=lambda s: True)
    checker.define_invariant("b", InvariantKind.LIVENESS, checker=lambda s: True)
    results = checker.check_all({"x": 1})
    assert len(results) == 2
    assert all(r.result == CheckResult.SATISFIED for r in results)


def test_check_transition_satisfied(checker):
    spec = checker.define_invariant(
        "monotonic", InvariantKind.MONOTONICITY,
        checker=lambda s: s["_after"]["counter"] >= s["_before"]["counter"],
    )
    result = checker.check_transition(spec.spec_id,
                                       before={"counter": 5},
                                       after={"counter": 7})
    assert result.result == CheckResult.SATISFIED


def test_check_transition_violated(checker):
    spec = checker.define_invariant(
        "monotonic", InvariantKind.MONOTONICITY,
        checker=lambda s: s["_after"]["counter"] >= s["_before"]["counter"],
    )
    result = checker.check_transition(spec.spec_id,
                                       before={"counter": 10},
                                       after={"counter": 3})
    assert result.result == CheckResult.VIOLATED
    violations = checker.get_violations()
    assert len(violations) == 1
    assert violations[0].state_before == {"counter": 10}


def test_check_transition_disabled(checker):
    spec = checker.define_invariant("x", InvariantKind.SAFETY, checker=lambda s: True)
    checker.disable_invariant(spec.spec_id)
    result = checker.check_transition(spec.spec_id, {}, {})
    assert result.result == CheckResult.SKIPPED


def test_prove_bounded_holds(checker):
    spec = checker.define_invariant(
        "always_positive", InvariantKind.SAFETY,
        checker=lambda s: s["val"] > 0,
    )
    states = [{"val": i} for i in range(1, 11)]
    proof = checker.prove_bounded(spec.spec_id, states)
    assert proof.holds is True
    assert proof.steps_verified == 10


def test_prove_bounded_counterexample(checker):
    spec = checker.define_invariant(
        "always_positive", InvariantKind.SAFETY,
        checker=lambda s: s["val"] > 0,
    )
    states = [{"val": 5}, {"val": 3}, {"val": -1}, {"val": 2}]
    proof = checker.prove_bounded(spec.spec_id, states)
    assert proof.holds is False
    assert "Counterexample at step 2" in proof.witness


def test_prove_bounded_no_spec(checker):
    proof = checker.prove_bounded("missing", [{"x": 1}])
    assert proof.holds is False


def test_prove_bounded_checker_error(checker):
    spec = checker.define_invariant(
        "bad", InvariantKind.SAFETY,
        checker=lambda s: s["missing"],
    )
    proof = checker.prove_bounded(spec.spec_id, [{"x": 1}])
    assert proof.holds is False
    assert "Error at step 0" in proof.witness


def test_get_violations_filter_severity(checker):
    spec = checker.define_invariant(
        "warn", InvariantKind.FAIRNESS,
        severity=ViolationSeverity.WARNING,
        checker=lambda s: False,
    )
    checker.check(spec.spec_id, {})
    assert len(checker.get_violations(severity=ViolationSeverity.WARNING)) == 1
    assert len(checker.get_violations(severity=ViolationSeverity.FATAL)) == 0


def test_get_proofs_filter(checker):
    s1 = checker.define_invariant("a", InvariantKind.SAFETY, checker=lambda s: True)
    s2 = checker.define_invariant("b", InvariantKind.SAFETY, checker=lambda s: True)
    checker.prove_bounded(s1.spec_id, [{"x": 1}])
    checker.prove_bounded(s2.spec_id, [{"x": 1}])
    assert len(checker.get_proofs()) == 2
    assert len(checker.get_proofs(spec_id=s1.spec_id)) == 1


def test_get_stats(checker):
    spec = checker.define_invariant(
        "test", InvariantKind.SAFETY, checker=lambda s: s["ok"],
    )
    checker.check(spec.spec_id, {"ok": True})
    checker.check(spec.spec_id, {"ok": False})
    stats = checker.get_stats()
    assert stats.total_specs == 1
    assert stats.total_checks == 2
    assert stats.total_violations == 1
    assert stats.satisfaction_rate == pytest.approx(0.5)
    assert stats.by_kind["safety"] == 1


def test_stats_empty(checker):
    stats = checker.get_stats()
    assert stats.total_specs == 0
    assert stats.satisfaction_rate == 0.0


def test_invariant_kinds_coverage(checker):
    for kind in InvariantKind:
        spec = checker.define_invariant(f"test_{kind.value}", kind,
                                        checker=lambda s: True)
        result = checker.check(spec.spec_id, {})
        assert result.result == CheckResult.SATISFIED


def test_severity_levels(checker):
    for sev in ViolationSeverity:
        spec = checker.define_invariant(
            f"sev_{sev.value}", InvariantKind.SAFETY,
            severity=sev, checker=lambda s: False,
        )
        checker.check(spec.spec_id, {})
    violations = checker.get_violations()
    assert len(violations) == len(ViolationSeverity)
