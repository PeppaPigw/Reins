from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable

from reins.contracts.types import (
    ContractCheckResult,
    ContractClause,
    ContractDefinition,
    ContractKind,
    ContractStats,
    ContractViolation,
    EnforcementMode,
    ViolationSeverity,
)


class ContractEngine:
    """Runtime behavioral contract verification for agent interactions.

    Supports preconditions, postconditions, invariants, and state transition
    contracts with configurable enforcement modes.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, ContractDefinition] = {}
        self._checkers: dict[str, Callable[[dict[str, Any]], bool]] = {}
        self._results: list[ContractCheckResult] = []
        self._violation_log: list[ContractViolation] = []

    def register_contract(self, contract: ContractDefinition) -> None:
        self._contracts[contract.contract_id] = contract

    def register_checker(self, clause_id: str, fn: Callable[[dict[str, Any]], bool]) -> None:
        self._checkers[clause_id] = fn

    def check_contract(self, contract_id: str, context: dict[str, Any] | None = None) -> ContractCheckResult:
        contract = self._contracts.get(contract_id)
        if not contract:
            return ContractCheckResult(
                contract_id=contract_id,
                contract_name="unknown",
                passed=False,
                violations=(ContractViolation(
                    clause_id="",
                    clause_name="",
                    kind=ContractKind.INVARIANT,
                    severity=ViolationSeverity.ERROR,
                    message=f"Contract '{contract_id}' not found",
                ),),
            )

        ctx = context or {}
        start = time.perf_counter()
        violations: list[ContractViolation] = []
        checked = 0

        for clause in contract.clauses:
            checker = self._checkers.get(clause.clause_id)
            if not checker:
                continue

            checked += 1
            try:
                passed = checker(ctx)
            except Exception as e:
                passed = False
                violations.append(ContractViolation(
                    clause_id=clause.clause_id,
                    clause_name=clause.name,
                    kind=clause.kind,
                    severity=clause.severity,
                    message=f"Checker raised: {e}",
                    context=ctx,
                ))
                continue

            if not passed:
                violations.append(ContractViolation(
                    clause_id=clause.clause_id,
                    clause_name=clause.name,
                    kind=clause.kind,
                    severity=clause.severity,
                    message=f"Clause '{clause.name}' failed",
                    context=ctx,
                ))

        duration = (time.perf_counter() - start) * 1000
        self._violation_log.extend(violations)

        result = ContractCheckResult(
            contract_id=contract_id,
            contract_name=contract.name,
            passed=len(violations) == 0,
            violations=tuple(violations),
            clauses_checked=checked,
            clauses_passed=checked - len(violations),
            duration_ms=duration,
        )
        self._results.append(result)
        return result

    def check_preconditions(self, contract_id: str, context: dict[str, Any] | None = None) -> ContractCheckResult:
        return self._check_by_kind(contract_id, ContractKind.PRECONDITION, context)

    def check_postconditions(self, contract_id: str, context: dict[str, Any] | None = None) -> ContractCheckResult:
        return self._check_by_kind(contract_id, ContractKind.POSTCONDITION, context)

    def check_invariants(self, contract_id: str, context: dict[str, Any] | None = None) -> ContractCheckResult:
        return self._check_by_kind(contract_id, ContractKind.INVARIANT, context)

    def should_abort(self, result: ContractCheckResult) -> bool:
        contract = self._contracts.get(result.contract_id)
        if not contract:
            return False

        if contract.enforcement == EnforcementMode.ABORT:
            return not result.passed

        if contract.enforcement == EnforcementMode.ENFORCE:
            return any(v.severity == ViolationSeverity.CRITICAL for v in result.violations)

        return False

    def get_violations(self, contract_id: str | None = None,
                       severity: ViolationSeverity | None = None) -> list[ContractViolation]:
        violations = self._violation_log
        if contract_id:
            clause_ids = set()
            contract = self._contracts.get(contract_id)
            if contract:
                clause_ids = {c.clause_id for c in contract.clauses}
            violations = [v for v in violations if v.clause_id in clause_ids]
        if severity:
            violations = [v for v in violations if v.severity == severity]
        return violations

    def get_stats(self) -> ContractStats:
        if not self._results:
            return ContractStats(total_contracts=len(self._contracts))

        total_checks = len(self._results)
        passed = sum(1 for r in self._results if r.passed)

        by_kind: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        for v in self._violation_log:
            by_kind[v.kind.value] += 1
            by_severity[v.severity.value] += 1

        return ContractStats(
            total_contracts=len(self._contracts),
            total_checks=total_checks,
            total_violations=len(self._violation_log),
            pass_rate=passed / total_checks if total_checks else 0.0,
            violations_by_kind=dict(by_kind),
            violations_by_severity=dict(by_severity),
        )

    def _check_by_kind(self, contract_id: str, kind: ContractKind,
                       context: dict[str, Any] | None = None) -> ContractCheckResult:
        contract = self._contracts.get(contract_id)
        if not contract:
            return ContractCheckResult(
                contract_id=contract_id,
                contract_name="unknown",
                passed=False,
            )

        filtered_clauses = [c for c in contract.clauses if c.kind == kind]
        filtered_contract = ContractDefinition(
            contract_id=contract.contract_id,
            name=contract.name,
            description=contract.description,
            clauses=tuple(filtered_clauses),
            enforcement=contract.enforcement,
        )

        original = self._contracts[contract_id]
        self._contracts[contract_id] = filtered_contract
        result = self.check_contract(contract_id, context)
        self._contracts[contract_id] = original
        return result
