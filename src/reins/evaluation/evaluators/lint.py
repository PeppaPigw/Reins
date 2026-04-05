"""Lint evaluator — runs ruff on the codebase and returns structured results."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import ulid

from reins.evaluation.evaluators.base import EvalResult, Evaluator
from reins.kernel.types import FailureClass


class LintEvaluator(Evaluator):
    """Runs ruff lint on a target path and returns pass/fail with details."""

    async def evaluate(self, context: dict) -> EvalResult:
        target = context.get("target", "src/")
        cwd = context.get("cwd", ".")
        run_id = context.get("run_id", "unknown")
        command_id = context.get("command_id")

        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "ruff", "check", target, "--output-format=text",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        passed = (proc.returncode or 0) == 0
        details = stdout.strip() if not passed else "no lint issues"

        return EvalResult(
            eval_id=str(ulid.new()),
            run_id=run_id,
            command_id=command_id,
            evaluator_kind="lint",
            passed=passed,
            score=1.0 if passed else 0.0,
            failure_class=None if passed else FailureClass.logic_failure,
            details=details,
            repair_hints=self._extract_hints(stdout) if not passed else [],
            ts=datetime.now(UTC),
        )

    @staticmethod
    def _extract_hints(output: str) -> list[str]:
        """Extract unique ruff error codes as repair hints."""
        hints: set[str] = set()
        for line in output.splitlines():
            # ruff output format: path:line:col: E123 message
            parts = line.split(":")
            if len(parts) >= 4:
                code_part = parts[3].strip().split(" ")
                if code_part:
                    hints.add(code_part[0])
        return sorted(hints)
