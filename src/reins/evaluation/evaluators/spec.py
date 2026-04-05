"""Spec evaluator — checks that implementation artifacts match spec contracts.

This evaluator compares the actual codebase structure against the
declarations in .trellis/spec/ to verify structural compliance.
E.g., does every adapter implement the full handle lifecycle?
Does the reducer avoid I/O imports?
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path

import ulid

from reins.evaluation.evaluators.base import EvalResult, Evaluator
from reins.kernel.types import FailureClass


class SpecEvaluator(Evaluator):
    """Structural compliance checker against spec contracts."""

    REQUIRED_ADAPTER_METHODS = frozenset({
        "open", "exec", "snapshot", "freeze", "thaw", "reset", "close",
    })

    FORBIDDEN_REDUCER_IMPORTS = frozenset({
        "aiofiles", "asyncio", "subprocess", "os", "shutil", "requests", "aiohttp",
    })

    async def evaluate(self, context: dict) -> EvalResult:
        cwd = Path(context.get("cwd", "."))
        run_id = context.get("run_id", "unknown")
        command_id = context.get("command_id")

        violations: list[str] = []
        violations.extend(self._check_adapters(cwd))
        violations.extend(self._check_reducer_purity(cwd))
        violations.extend(self._check_module_structure(cwd))

        passed = len(violations) == 0
        return EvalResult(
            eval_id=str(ulid.new()),
            run_id=run_id,
            command_id=command_id,
            evaluator_kind="spec",
            passed=passed,
            score=1.0 if passed else max(0.0, 1.0 - 0.1 * len(violations)),
            failure_class=None if passed else FailureClass.logic_failure,
            details="\n".join(violations) if violations else "all spec checks passed",
            repair_hints=violations,
            ts=datetime.now(UTC),
        )

    def _check_adapters(self, cwd: Path) -> list[str]:
        """Verify all adapter files implement the full handle lifecycle."""
        violations: list[str] = []
        adapter_dir = cwd / "src" / "reins" / "execution" / "adapters"
        if not adapter_dir.is_dir():
            return ["adapters directory missing"]

        for py_file in adapter_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                violations.append(f"{py_file.name}: syntax error")
                continue

            class_methods: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    class_methods.add(node.name)

            missing = self.REQUIRED_ADAPTER_METHODS - class_methods
            if missing:
                violations.append(
                    f"{py_file.name}: missing adapter methods: {sorted(missing)}"
                )
        return violations

    def _check_reducer_purity(self, cwd: Path) -> list[str]:
        """Verify the reducer has no I/O imports."""
        violations: list[str] = []
        reducer = cwd / "src" / "reins" / "kernel" / "reducer" / "reducer.py"
        if not reducer.is_file():
            return ["reducer.py not found"]

        try:
            tree = ast.parse(reducer.read_text(encoding="utf-8"))
        except SyntaxError:
            return ["reducer.py: syntax error"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.FORBIDDEN_REDUCER_IMPORTS:
                        violations.append(f"reducer imports I/O module: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in self.FORBIDDEN_REDUCER_IMPORTS:
                    violations.append(f"reducer imports I/O module: {node.module}")
        return violations

    def _check_module_structure(self, cwd: Path) -> list[str]:
        """Verify required kernel modules exist."""
        violations: list[str] = []
        required = [
            "src/reins/kernel/types.py",
            "src/reins/kernel/event/envelope.py",
            "src/reins/kernel/event/journal.py",
            "src/reins/kernel/reducer/reducer.py",
            "src/reins/kernel/reducer/state.py",
            "src/reins/kernel/routing/router.py",
            "src/reins/policy/engine.py",
        ]
        for path in required:
            if not (cwd / path).is_file():
                violations.append(f"missing required module: {path}")
        return violations
