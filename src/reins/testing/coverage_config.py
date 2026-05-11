"""Coverage configuration and reporting utilities for Reins.

Defines per-module coverage targets and utilities for parsing,
checking, and formatting coverage reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CoverageTarget:
    """A coverage threshold target for a specific module."""

    module_path: str
    min_coverage: float
    description: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_coverage <= 100.0:
            raise ValueError(f"min_coverage must be 0-100, got {self.min_coverage}")


COVERAGE_TARGETS: list[CoverageTarget] = [
    CoverageTarget("reins.kernel", 90.0, "Event-sourced kernel"),
    CoverageTarget("reins.policy", 90.0, "Policy engine"),
    CoverageTarget("reins.execution", 85.0, "Execution adapters"),
    CoverageTarget("reins.context", 85.0, "Context compilation"),
    CoverageTarget("reins.workflow", 85.0, "Workflow state machine"),
    CoverageTarget("reins.packaging", 80.0, "Packaging utilities"),
    CoverageTarget("reins.integrations", 75.0, "External integrations"),
]


@dataclass
class CoverageReport:
    """Coverage measurement result for a single module."""

    module: str
    statements: int
    missed: int
    coverage_percent: float
    target_percent: float
    passed: bool

    @property
    def covered(self) -> int:
        return self.statements - self.missed


def _find_target(module_path: str) -> CoverageTarget | None:
    """Find the coverage target that matches a given module path."""
    for target in COVERAGE_TARGETS:
        if module_path.startswith(target.module_path):
            return target
    return None


def parse_coverage_json(coverage_json_path: Path) -> list[CoverageReport]:
    """Parse pytest-cov JSON output into a list of CoverageReport.

    The JSON file is expected to follow the coverage.py JSON format with
    a top-level 'files' dict mapping file paths to coverage data.

    Args:
        coverage_json_path: Path to the coverage.json file.

    Returns:
        List of CoverageReport, one per matched target module.

    Raises:
        FileNotFoundError: If the coverage JSON file does not exist.
    """
    if not coverage_json_path.exists():
        raise FileNotFoundError(f"Coverage JSON not found: {coverage_json_path}")

    data = json.loads(coverage_json_path.read_text())
    files_data = data.get("files", {})

    # Aggregate stats per target module
    module_stats: dict[str, dict[str, int]] = {}
    for target in COVERAGE_TARGETS:
        module_stats[target.module_path] = {"statements": 0, "missed": 0}

    for file_path, file_info in files_data.items():
        # Convert file path to module path (src/reins/kernel/foo.py -> reins.kernel.foo)
        normalized = file_path.replace("/", ".").replace("\\", ".")
        if "src.reins." in normalized:
            module_path = normalized.split("src.reins.", 1)[1]
            module_path = "reins." + module_path.removesuffix(".py")
        elif "reins." in normalized:
            module_path = "reins." + normalized.split("reins.", 1)[1].removesuffix(".py")
        else:
            continue

        target = _find_target(module_path)
        if target is None:
            continue

        summary = file_info.get("summary", {})
        module_stats[target.module_path]["statements"] += summary.get(
            "num_statements", 0
        )
        module_stats[target.module_path]["missed"] += summary.get("missing_lines", 0)

    reports: list[CoverageReport] = []
    for target in COVERAGE_TARGETS:
        stats = module_stats[target.module_path]
        stmts = stats["statements"]
        missed = stats["missed"]
        if stmts > 0:
            pct = ((stmts - missed) / stmts) * 100.0
        else:
            pct = 100.0
        reports.append(
            CoverageReport(
                module=target.module_path,
                statements=stmts,
                missed=missed,
                coverage_percent=round(pct, 2),
                target_percent=target.min_coverage,
                passed=pct >= target.min_coverage,
            )
        )

    return reports


def check_coverage_gates(reports: list[CoverageReport]) -> tuple[bool, list[str]]:
    """Check whether all coverage reports meet their targets.

    Args:
        reports: List of CoverageReport to evaluate.

    Returns:
        Tuple of (all_passed, list of failure messages).
    """
    failures: list[str] = []
    for report in reports:
        if not report.passed:
            failures.append(
                f"{report.module}: {report.coverage_percent:.1f}% < "
                f"{report.target_percent:.1f}% target"
            )
    return len(failures) == 0, failures


def format_coverage_table(reports: list[CoverageReport]) -> str:
    """Render coverage reports as an ASCII table with pass/fail indicators.

    Args:
        reports: List of CoverageReport to format.

    Returns:
        Formatted ASCII table string.
    """
    header = f"{'Module':<25} {'Stmts':>6} {'Miss':>6} {'Cover':>7} {'Target':>7} {'Status':<6}"
    separator = "-" * len(header)
    lines = [header, separator]

    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        lines.append(
            f"{report.module:<25} {report.statements:>6} {report.missed:>6} "
            f"{report.coverage_percent:>6.1f}% {report.target_percent:>6.1f}% {status:<6}"
        )

    lines.append(separator)
    return "\n".join(lines)
