from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import re
import sys
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

from reins.outcomes.types import (
    GuardType,
    OutcomeResult,
    OutcomeSpec,
    PredicateResult,
    PredicateType,
    RegressionGuard,
    RegressionResult,
    VerificationPredicate,
    utc_now,
)

CustomPredicate = Callable[[str, Any, dict[str, Any]], bool | float | dict[str, Any] | Awaitable[Any]]


class OutcomeVerifier:
    """Evaluates outcome specifications against the current state."""

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def verify(self, spec: OutcomeSpec, context: dict[str, Any]) -> OutcomeResult:
        predicate_results = [
            await self.verify_predicate(predicate, context) for predicate in spec.predicates
        ]
        regression_results = [
            await self.check_regression(guard, context) for guard in spec.regression_guards
        ]
        partial_progress = await self.compute_partial_progress(predicate_results)
        score = partial_progress if spec.partial_credit else float(all(r.passed for r in predicate_results))
        regression_score = self._score_regressions(regression_results)
        overall_score = min(score, regression_score)

        required_failed = any(result.required and not result.passed for result in predicate_results)
        regression_failed = any(not result.passed for result in regression_results)
        deadline_missed = spec.deadline is not None and utc_now() > spec.deadline
        passed = (
            not required_failed
            and not regression_failed
            and not deadline_missed
            and overall_score >= spec.acceptance_threshold
        )

        return OutcomeResult(
            outcome_id=spec.outcome_id,
            overall_score=overall_score,
            passed=passed,
            predicate_results=tuple(predicate_results),
            regression_results=tuple(regression_results),
            partial_progress=partial_progress,
            evidence={
                "acceptance_threshold": spec.acceptance_threshold,
                "deadline": spec.deadline.isoformat() if spec.deadline is not None else None,
                "deadline_missed": deadline_missed,
                "required_failed": required_failed,
                "regression_failed": regression_failed,
                "predicate_count": len(predicate_results),
                "regression_guard_count": len(regression_results),
                "task_id": spec.task_id,
            },
            evaluated_at=utc_now(),
        )

    async def verify_predicate(
        self,
        pred: VerificationPredicate,
        context: dict[str, Any],
    ) -> PredicateResult:
        try:
            if pred.predicate_type is PredicateType.FILE_EXISTS:
                passed, score, evidence = await self._verify_file_exists(
                    pred.target,
                    pred.expected,
                    context,
                )
            elif pred.predicate_type is PredicateType.TEST_PASSES:
                passed, score, evidence = await self._verify_test_passes(
                    pred.target,
                    pred.expected,
                    context,
                )
            elif pred.predicate_type is PredicateType.PATTERN_MATCHES:
                passed, score, evidence = await self._verify_pattern_matches(
                    pred.target,
                    pred.expected,
                    context,
                )
            elif pred.predicate_type is PredicateType.METRIC_THRESHOLD:
                passed, score, evidence = await self._verify_metric_threshold(
                    pred.target,
                    pred.expected,
                    context,
                )
            elif pred.predicate_type is PredicateType.CUSTOM_FUNCTION:
                passed, score, evidence = await self._verify_custom_function(
                    pred.target,
                    pred.expected,
                    context,
                )
            elif pred.predicate_type is PredicateType.INVARIANT_HOLDS:
                passed, score, evidence = await self._verify_invariant_holds(
                    pred.target,
                    pred.expected,
                    context,
                )
            else:
                raise ValueError(f"unsupported predicate type: {pred.predicate_type}")
            return PredicateResult(
                predicate_id=pred.predicate_id,
                passed=passed,
                score=score,
                weight=pred.weight,
                required=pred.required,
                evidence=evidence,
                evaluated_at=utc_now(),
            )
        except Exception as exc:
            return PredicateResult(
                predicate_id=pred.predicate_id,
                passed=False,
                score=0.0,
                weight=pred.weight,
                required=pred.required,
                evidence={"predicate_type": pred.predicate_type.value, "target": pred.target},
                error=str(exc),
                evaluated_at=utc_now(),
            )

    async def check_regression(
        self,
        guard: RegressionGuard,
        context: dict[str, Any],
    ) -> RegressionResult:
        try:
            if guard.guard_type is GuardType.TEST_SUITE:
                passed, score, observed, deviation, evidence = await self._check_test_suite(
                    guard,
                    context,
                )
            elif guard.guard_type is GuardType.METRIC_FLOOR:
                passed, score, observed, deviation, evidence = await self._check_metric_floor(
                    guard,
                    context,
                )
            elif guard.guard_type is GuardType.FILE_UNCHANGED:
                passed, score, observed, deviation, evidence = await self._check_file_unchanged(
                    guard,
                    context,
                )
            elif guard.guard_type is GuardType.API_CONTRACT:
                passed, score, observed, deviation, evidence = await self._check_api_contract(
                    guard,
                    context,
                )
            else:
                raise ValueError(f"unsupported guard type: {guard.guard_type}")
            return RegressionResult(
                guard_id=guard.guard_id,
                guard_type=guard.guard_type,
                passed=passed,
                score=score,
                baseline=guard.baseline,
                observed=observed,
                deviation=deviation,
                tolerance=guard.tolerance,
                evidence=evidence,
                evaluated_at=utc_now(),
            )
        except Exception as exc:
            return RegressionResult(
                guard_id=guard.guard_id,
                guard_type=guard.guard_type,
                passed=False,
                score=0.0,
                baseline=guard.baseline,
                tolerance=guard.tolerance,
                evidence={"guard_type": guard.guard_type.value},
                error=str(exc),
                evaluated_at=utc_now(),
            )

    async def compute_partial_progress(self, results: list[PredicateResult]) -> float:
        if not results:
            return 0.0
        total_weight = sum(result.weight for result in results)
        if total_weight <= 0.0:
            return 0.0
        weighted_score = sum(result.score * result.weight for result in results)
        return self._clamp(weighted_score / total_weight)

    async def _verify_file_exists(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        path = self._resolve_path(target, context)
        exists = path.exists()
        evidence: dict[str, Any] = {
            "path": str(path),
            "exists": exists,
            "kind": "directory" if path.is_dir() else "file" if exists else "missing",
        }
        if expected is False:
            return not exists, 1.0 if not exists else 0.0, evidence
        if not exists:
            return False, 0.0, evidence
        if expected in (None, True):
            return True, 1.0, evidence
        if path.is_dir():
            return True, 1.0, evidence

        text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        content_passed, content_score, content_evidence = self._match_expected(text, expected)
        evidence.update(content_evidence)
        return content_passed, content_score, evidence

    async def _verify_test_passes(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        command = self._build_test_command(target, expected, context)
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd(context),
            env=self._subprocess_env(context),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout(context),
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return False, 0.0, {"command": command, "timed_out": True}

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        passed_count, failed_count = self._parse_pytest_counts(stdout + "\n" + stderr)
        return_code = proc.returncode or 0
        passed = return_code == 0 and failed_count == 0
        total = passed_count + failed_count
        score = 1.0 if passed else passed_count / total if total > 0 else 0.0
        return passed, self._clamp(score), {
            "command": command,
            "returncode": return_code,
            "passed_count": passed_count,
            "failed_count": failed_count,
        }

    async def _verify_pattern_matches(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        path = self._resolve_path(target, context)
        if not path.exists() or not path.is_file():
            return False, 0.0, {"path": str(path), "exists": path.exists()}
        text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        passed, score, evidence = self._match_expected(text, expected)
        evidence["path"] = str(path)
        return passed, score, evidence

    async def _verify_metric_threshold(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        metrics = context.get("metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("context['metrics'] must be a mapping")
        observed = metrics.get(target)
        if observed is None:
            return False, 0.0, {"metric": target, "observed": None}
        passed, score, evidence = self._compare_metric(float(observed), expected)
        evidence.update({"metric": target, "observed": observed})
        return passed, score, evidence

    async def _verify_custom_function(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        functions = context.get("custom_functions", {})
        if not isinstance(functions, dict) or target not in functions:
            raise ValueError(f"custom function is not registered: {target}")
        function = functions[target]
        if not callable(function):
            raise ValueError(f"custom function is not callable: {target}")

        outcome = function(target, expected, context)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        passed, score, evidence = self._coerce_custom_outcome(outcome)
        evidence["function"] = target
        return passed, score, evidence

    async def _verify_invariant_holds(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> tuple[bool, float, dict[str, Any]]:
        path = self._resolve_path(target, context)
        files = await asyncio.to_thread(self._collect_files, path)
        invariant = expected if isinstance(expected, dict) else {"forbid_patterns": expected}
        forbidden = invariant.get("forbid_patterns") or invariant.get("forbid_imports") or ()
        required = invariant.get("require_patterns") or ()

        forbidden_patterns = self._as_tuple(forbidden)
        required_patterns = self._as_tuple(required)
        forbidden_hits: list[str] = []
        required_seen = {pattern: False for pattern in required_patterns}

        for file_path in files:
            text = await asyncio.to_thread(
                file_path.read_text,
                encoding="utf-8",
                errors="replace",
            )
            for pattern in forbidden_patterns:
                if re.search(pattern, text, re.MULTILINE):
                    forbidden_hits.append(f"{file_path}:{pattern}")
            for pattern in required_patterns:
                if re.search(pattern, text, re.MULTILINE):
                    required_seen[pattern] = True

        missing_required = [pattern for pattern, seen in required_seen.items() if not seen]
        total_checks = len(forbidden_patterns) + len(required_patterns)
        failures = len(forbidden_hits) + len(missing_required)
        passed = failures == 0
        score = 1.0 if total_checks == 0 else (total_checks - min(failures, total_checks)) / total_checks
        return passed, self._clamp(score), {
            "path": str(path),
            "files_checked": len(files),
            "forbidden_hits": forbidden_hits,
            "missing_required": missing_required,
        }

    async def _check_test_suite(
        self,
        guard: RegressionGuard,
        context: dict[str, Any],
    ) -> tuple[bool, float, Any, float | None, dict[str, Any]]:
        target = self._guard_target(guard)
        passed, score, evidence = await self._verify_test_passes(target, True, context)
        observed = {"score": score, "passed": passed}
        return passed, score, observed, 1.0 - score, evidence

    async def _check_metric_floor(
        self,
        guard: RegressionGuard,
        context: dict[str, Any],
    ) -> tuple[bool, float, Any, float | None, dict[str, Any]]:
        baseline = guard.baseline
        metric_name = str(baseline.get("metric") if isinstance(baseline, dict) else "")
        floor_value = self._first_present(baseline, ("value", "floor", "min"))
        floor = float(floor_value if isinstance(baseline, dict) else baseline)
        metrics = context.get("metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("context['metrics'] must be a mapping")
        observed_value = metrics.get(metric_name) if metric_name else metrics.get(guard.guard_id)
        if observed_value is None:
            raise ValueError(f"metric is missing for regression guard: {metric_name or guard.guard_id}")
        observed = float(observed_value)
        deviation = max(floor - observed, 0.0)
        passed = observed + guard.tolerance >= floor
        score = 1.0 if passed else self._ratio_score(observed, floor)
        return passed, score, observed, deviation, {
            "metric": metric_name or guard.guard_id,
            "floor": floor,
            "observed": observed,
        }

    async def _check_file_unchanged(
        self,
        guard: RegressionGuard,
        context: dict[str, Any],
    ) -> tuple[bool, float, Any, float | None, dict[str, Any]]:
        baseline = guard.baseline
        target = baseline.get("path") if isinstance(baseline, dict) else guard.guard_id
        expected_hash = baseline.get("sha256") if isinstance(baseline, dict) else baseline
        path = self._resolve_path(str(target), context)
        if not path.exists() or not path.is_file():
            return False, 0.0, None, None, {"path": str(path), "exists": path.exists()}
        observed_hash = await asyncio.to_thread(self._sha256, path)
        passed = observed_hash == expected_hash
        return passed, 1.0 if passed else 0.0, observed_hash, 0.0 if passed else 1.0, {
            "path": str(path),
            "sha256": observed_hash,
        }

    async def _check_api_contract(
        self,
        guard: RegressionGuard,
        context: dict[str, Any],
    ) -> tuple[bool, float, Any, float | None, dict[str, Any]]:
        contracts = context.get("api_contracts", {})
        if not isinstance(contracts, dict):
            raise ValueError("context['api_contracts'] must be a mapping")
        observed = contracts.get(guard.guard_id)
        if observed is None and isinstance(guard.baseline, dict):
            observed = contracts.get(guard.baseline.get("name"))
        passed = observed == guard.baseline
        return passed, 1.0 if passed else 0.0, observed, 0.0 if passed else 1.0, {
            "contract": guard.guard_id,
        }

    def _resolve_path(self, target: str, context: dict[str, Any]) -> Path:
        path = Path(target)
        if path.is_absolute():
            return path
        return (Path(self._cwd(context)) / path).resolve()

    def _cwd(self, context: dict[str, Any]) -> str:
        return str(context.get("cwd") or context.get("repo") or context.get("root") or ".")

    def _timeout(self, context: dict[str, Any]) -> float:
        return float(context.get("timeout_seconds", self.timeout_seconds))

    def _subprocess_env(self, context: dict[str, Any]) -> dict[str, str]:
        extra_env = context.get("env", {})
        if extra_env is not None and not isinstance(extra_env, dict):
            raise ValueError("context['env'] must be a mapping")
        return os.environ | {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"} | (extra_env or {})

    def _build_test_command(
        self,
        target: str,
        expected: Any,
        context: dict[str, Any],
    ) -> list[str]:
        python = str(context.get("python", sys.executable))
        if isinstance(expected, dict) and expected.get("command"):
            command = expected["command"]
            if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                raise ValueError("expected['command'] must be a list of strings")
            return command
        args = [python, "-m", "pytest", target, "-q", "--tb=short"]
        if isinstance(expected, dict) and expected.get("pytest_args"):
            pytest_args = expected["pytest_args"]
            if not isinstance(pytest_args, list) or not all(
                isinstance(item, str) for item in pytest_args
            ):
                raise ValueError("expected['pytest_args'] must be a list of strings")
            args.extend(pytest_args)
        return args

    def _match_expected(self, text: str, expected: Any) -> tuple[bool, float, dict[str, Any]]:
        if isinstance(expected, str):
            matched = re.search(expected, text, re.MULTILINE) is not None
            return matched, 1.0 if matched else 0.0, {"pattern": expected, "matched": matched}
        if isinstance(expected, dict):
            contains = self._as_tuple(expected.get("contains"))
            patterns = self._as_tuple(expected.get("patterns") or expected.get("pattern"))
            absent = self._as_tuple(expected.get("absent") or expected.get("not_contains"))
            checks = [needle in text for needle in contains]
            checks.extend(re.search(pattern, text, re.MULTILINE) is not None for pattern in patterns)
            checks.extend(needle not in text for needle in absent)
            if not checks:
                return True, 1.0, {"matched": True}
            passed_count = sum(1 for check in checks if check)
            score = passed_count / len(checks)
            return score == 1.0, score, {
                "checks": len(checks),
                "passed_checks": passed_count,
            }
        if isinstance(expected, bool):
            passed = bool(text.strip()) is expected
            return passed, 1.0 if passed else 0.0, {"expected_non_empty": expected}
        return True, 1.0, {"matched": True}

    def _compare_metric(self, observed: float, expected: Any) -> tuple[bool, float, dict[str, Any]]:
        if isinstance(expected, dict):
            if "min" in expected:
                minimum = float(expected["min"])
                passed = observed >= minimum
                return passed, 1.0 if passed else self._ratio_score(observed, minimum), {
                    "operator": "min",
                    "threshold": minimum,
                }
            if "max" in expected:
                maximum = float(expected["max"])
                passed = observed <= maximum
                score = 1.0 if passed else self._ratio_score(maximum, observed)
                return passed, score, {"operator": "max", "threshold": maximum}
            if "equals" in expected:
                wanted = float(expected["equals"])
                tolerance = float(expected.get("tolerance", 0.0))
                deviation = abs(observed - wanted)
                passed = deviation <= tolerance
                score = 1.0 if passed else self._ratio_score(max(wanted - deviation, 0.0), wanted)
                return passed, score, {
                    "operator": "equals",
                    "expected": wanted,
                    "deviation": deviation,
                    "tolerance": tolerance,
                }
        minimum = float(expected)
        passed = observed >= minimum
        return passed, 1.0 if passed else self._ratio_score(observed, minimum), {
            "operator": "min",
            "threshold": minimum,
        }

    def _coerce_custom_outcome(self, outcome: Any) -> tuple[bool, float, dict[str, Any]]:
        if isinstance(outcome, bool):
            return outcome, 1.0 if outcome else 0.0, {"returned": outcome}
        if isinstance(outcome, int | float):
            score = self._clamp(float(outcome))
            return score >= 1.0, score, {"returned_score": score}
        if isinstance(outcome, dict):
            passed = bool(outcome.get("passed", outcome.get("score", 0.0) >= 1.0))
            score = self._clamp(float(outcome.get("score", 1.0 if passed else 0.0)))
            evidence = outcome.get("evidence", {})
            if not isinstance(evidence, dict):
                evidence = {"value": evidence}
            return passed, score, evidence
        raise ValueError("custom predicate must return bool, float, or dict")

    @staticmethod
    def _parse_pytest_counts(output: str) -> tuple[int, int]:
        passed = sum(int(match) for match in re.findall(r"(\d+) passed", output))
        failed = sum(int(match) for match in re.findall(r"(\d+) failed", output))
        return passed, failed

    @staticmethod
    def _collect_files(path: Path) -> list[Path]:
        if path.is_file():
            return [path]
        if not path.exists():
            return []
        return sorted(
            item
            for item in path.rglob("*.py")
            if item.is_file() and ".venv" not in item.parts and "__pycache__" not in item.parts
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _guard_target(guard: RegressionGuard) -> str:
        if isinstance(guard.baseline, dict) and guard.baseline.get("target"):
            return str(guard.baseline["target"])
        return str(guard.baseline)

    @staticmethod
    def _first_present(mapping: Any, keys: tuple[str, ...]) -> Any:
        if not isinstance(mapping, dict):
            return mapping
        for key in keys:
            if key in mapping:
                return mapping[key]
        raise ValueError(f"mapping must include one of: {', '.join(keys)}")

    @staticmethod
    def _score_regressions(results: list[RegressionResult]) -> float:
        if not results:
            return 1.0
        return min(result.score for result in results)

    @staticmethod
    def _as_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Iterable):
            return tuple(str(item) for item in value)
        return (str(value),)

    @staticmethod
    def _ratio_score(numerator: float, denominator: float) -> float:
        if denominator <= 0.0:
            return 1.0 if numerator >= denominator else 0.0
        return OutcomeVerifier._clamp(numerator / denominator)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
