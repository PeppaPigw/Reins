from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from reins.invariants.types import (
    CheckResult,
    InvariantCheck,
    InvariantKind,
    InvariantSpec,
    InvariantStats,
    SafetyProof,
    Violation,
    ViolationSeverity,
)


class InvariantChecker:
    """Runtime invariant verification with formal property checking.

    Defines safety/liveness/fairness invariants, checks them against system state,
    detects violations, and constructs bounded safety proofs through exhaustive
    state exploration.
    """

    def __init__(self) -> None:
        self._specs: dict[str, InvariantSpec] = {}
        self._checks: list[InvariantCheck] = []
        self._violations: list[Violation] = []
        self._proofs: list[SafetyProof] = []
        self._checkers: dict[str, Callable[[dict[str, Any]], bool]] = {}

    def define_invariant(self, name: str, kind: InvariantKind,
                         description: str = "", expression: str = "",
                         severity: ViolationSeverity = ViolationSeverity.ERROR,
                         checker: Callable[[dict[str, Any]], bool] | None = None) -> InvariantSpec:
        spec = InvariantSpec(
            name=name,
            kind=kind,
            description=description,
            expression=expression,
            severity=severity,
        )
        self._specs[spec.spec_id] = spec
        if checker:
            self._checkers[spec.spec_id] = checker
        return spec

    def get_spec(self, spec_id: str) -> InvariantSpec | None:
        return self._specs.get(spec_id)

    def disable_invariant(self, spec_id: str) -> InvariantSpec | None:
        spec = self._specs.get(spec_id)
        if not spec:
            return None
        updated = spec.model_copy(update={"enabled": False})
        self._specs[spec_id] = updated
        return updated

    def enable_invariant(self, spec_id: str) -> InvariantSpec | None:
        spec = self._specs.get(spec_id)
        if not spec:
            return None
        updated = spec.model_copy(update={"enabled": True})
        self._specs[spec_id] = updated
        return updated

    def check(self, spec_id: str, state: dict[str, Any]) -> InvariantCheck:
        spec = self._specs.get(spec_id)
        if not spec:
            check = InvariantCheck(spec_id=spec_id, result=CheckResult.SKIPPED,
                                   message="Spec not found")
            self._checks.append(check)
            return check

        if not spec.enabled:
            check = InvariantCheck(spec_id=spec_id, result=CheckResult.SKIPPED,
                                   message="Invariant disabled")
            self._checks.append(check)
            return check

        checker = self._checkers.get(spec_id)
        if not checker:
            check = InvariantCheck(spec_id=spec_id, result=CheckResult.UNKNOWN,
                                   context=state, message="No checker registered")
            self._checks.append(check)
            return check

        try:
            holds = checker(state)
            result = CheckResult.SATISFIED if holds else CheckResult.VIOLATED
            message = "" if holds else f"Invariant '{spec.name}' violated"
        except Exception as e:
            result = CheckResult.UNKNOWN
            message = f"Checker error: {str(e)}"

        check = InvariantCheck(spec_id=spec_id, result=result,
                               context=state, message=message)
        self._checks.append(check)

        if result == CheckResult.VIOLATED:
            self._violations.append(Violation(
                spec_id=spec_id,
                severity=spec.severity,
                state_after=state,
                message=message,
            ))

        return check

    def check_all(self, state: dict[str, Any]) -> list[InvariantCheck]:
        results = []
        for spec_id in self._specs:
            results.append(self.check(spec_id, state))
        return results

    def check_transition(self, spec_id: str, before: dict[str, Any],
                         after: dict[str, Any]) -> InvariantCheck:
        spec = self._specs.get(spec_id)
        if not spec or not spec.enabled:
            return self.check(spec_id, after)

        checker = self._checkers.get(spec_id)
        if not checker:
            return self.check(spec_id, after)

        combined_state = {"_before": before, "_after": after, **after}
        try:
            holds = checker(combined_state)
            result = CheckResult.SATISFIED if holds else CheckResult.VIOLATED
            message = "" if holds else f"Transition violates '{spec.name}'"
        except Exception as e:
            result = CheckResult.UNKNOWN
            message = f"Checker error: {str(e)}"

        check = InvariantCheck(spec_id=spec_id, result=result,
                               context=combined_state, message=message)
        self._checks.append(check)

        if result == CheckResult.VIOLATED:
            self._violations.append(Violation(
                spec_id=spec_id,
                severity=spec.severity,
                state_before=before,
                state_after=after,
                message=message,
            ))

        return check

    def prove_bounded(self, spec_id: str,
                      states: list[dict[str, Any]]) -> SafetyProof:
        spec = self._specs.get(spec_id)
        checker = self._checkers.get(spec_id)

        if not spec or not checker:
            proof = SafetyProof(spec_id=spec_id, holds=False,
                                witness="No spec or checker")
            self._proofs.append(proof)
            return proof

        steps_verified = 0
        for state in states:
            try:
                if not checker(state):
                    proof = SafetyProof(
                        spec_id=spec_id, holds=False,
                        witness=f"Counterexample at step {steps_verified}: {state}",
                        steps_verified=steps_verified,
                    )
                    self._proofs.append(proof)
                    return proof
            except Exception:
                proof = SafetyProof(
                    spec_id=spec_id, holds=False,
                    witness=f"Error at step {steps_verified}",
                    steps_verified=steps_verified,
                )
                self._proofs.append(proof)
                return proof
            steps_verified += 1

        proof = SafetyProof(
            spec_id=spec_id, holds=True,
            witness=f"Verified over {steps_verified} states",
            steps_verified=steps_verified,
        )
        self._proofs.append(proof)
        return proof

    def get_violations(self, spec_id: str | None = None,
                       severity: ViolationSeverity | None = None) -> list[Violation]:
        violations = self._violations
        if spec_id:
            violations = [v for v in violations if v.spec_id == spec_id]
        if severity:
            violations = [v for v in violations if v.severity == severity]
        return violations

    def get_proofs(self, spec_id: str | None = None) -> list[SafetyProof]:
        proofs = self._proofs
        if spec_id:
            proofs = [p for p in proofs if p.spec_id == spec_id]
        return proofs

    def get_stats(self) -> InvariantStats:
        by_kind: dict[str, int] = defaultdict(int)
        for spec in self._specs.values():
            by_kind[spec.kind.value] += 1

        by_result: dict[str, int] = defaultdict(int)
        for check in self._checks:
            by_result[check.result.value] += 1

        satisfied = by_result.get(CheckResult.SATISFIED.value, 0)
        total_meaningful = satisfied + by_result.get(CheckResult.VIOLATED.value, 0)
        rate = satisfied / total_meaningful if total_meaningful > 0 else 0.0

        return InvariantStats(
            total_specs=len(self._specs),
            total_checks=len(self._checks),
            total_violations=len(self._violations),
            total_proofs=len(self._proofs),
            satisfaction_rate=rate,
            by_kind=dict(by_kind),
            by_result=dict(by_result),
        )
