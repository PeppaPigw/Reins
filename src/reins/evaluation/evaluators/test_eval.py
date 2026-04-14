"""Test evaluator — runs pytest and returns structured evaluation results."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import UTC, datetime

import ulid

from reins.evaluation.evaluators.base import EvalResult, Evaluator
from reins.kernel.types import FailureClass


class TestEvaluator(Evaluator):
    """Runs the test suite and reports structured results."""

    async def evaluate(self, context: dict) -> EvalResult:
        target = context.get("target", "tests/")
        cwd = context.get("cwd", ".")
        run_id = context.get("run_id", "unknown")
        command_id = context.get("command_id")
        python = context.get("python", sys.executable)
        env = os.environ | {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}

        proc = await asyncio.create_subprocess_exec(
            python, "-m", "pytest", target, "-v", "--tb=short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode("utf-8", errors="replace")

        passed_count, failed_count = self._parse_summary(stdout)
        all_passed = (proc.returncode or 0) == 0 and failed_count == 0
        total = passed_count + failed_count
        score = passed_count / total if total > 0 else 0.0

        failure_class = None
        if not all_passed:
            if "ModuleNotFoundError" in stdout or "ImportError" in stdout:
                failure_class = FailureClass.environment_failure
            else:
                failure_class = FailureClass.logic_failure

        failed_tests = self._extract_failed(stdout) if not all_passed else []

        return EvalResult(
            eval_id=str(ulid.new()),
            run_id=run_id,
            command_id=command_id,
            evaluator_kind="test",
            passed=all_passed,
            score=score,
            failure_class=failure_class,
            details=f"{passed_count} passed, {failed_count} failed",
            repair_hints=failed_tests,
            ts=datetime.now(UTC),
        )

    @staticmethod
    def _parse_summary(output: str) -> tuple[int, int]:
        """Parse pytest summary line for pass/fail counts."""
        passed = 0
        failed = 0
        match = re.search(r"(\d+) passed", output)
        if match:
            passed = int(match.group(1))
        match = re.search(r"(\d+) failed", output)
        if match:
            failed = int(match.group(1))
        return passed, failed

    @staticmethod
    def _extract_failed(output: str) -> list[str]:
        """Extract failed test names as repair hints."""
        failed: list[str] = []
        for line in output.splitlines():
            if "FAILED" in line:
                # pytest format: FAILED tests/test_foo.py::test_bar - ...
                parts = line.split(" ")
                for part in parts:
                    if "::" in part:
                        failed.append(part.strip())
                        break
        return failed
