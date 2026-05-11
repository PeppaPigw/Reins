"""Tests for reins.testing.coverage_config module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from reins.testing.coverage_config import (
    COVERAGE_TARGETS,
    CoverageReport,
    CoverageTarget,
    check_coverage_gates,
    format_coverage_table,
    parse_coverage_json,
)


def test_coverage_targets_defined():
    """COVERAGE_TARGETS should contain at least 5 module targets."""
    assert len(COVERAGE_TARGETS) >= 5
    assert all(isinstance(t, CoverageTarget) for t in COVERAGE_TARGETS)


def test_coverage_target_fields():
    """Each CoverageTarget should have valid fields."""
    for target in COVERAGE_TARGETS:
        assert target.module_path.startswith("reins.")
        assert 0.0 <= target.min_coverage <= 100.0
        assert len(target.description) > 0


def test_coverage_target_validation():
    """CoverageTarget should reject invalid min_coverage values."""
    import pytest

    with pytest.raises(ValueError):
        CoverageTarget("reins.foo", 101.0, "Invalid")
    with pytest.raises(ValueError):
        CoverageTarget("reins.foo", -1.0, "Invalid")


def test_coverage_report_passed_when_above_target():
    """CoverageReport.passed should be True when coverage >= target."""
    report = CoverageReport(
        module="reins.kernel",
        statements=100,
        missed=5,
        coverage_percent=95.0,
        target_percent=90.0,
        passed=True,
    )
    assert report.passed is True
    assert report.covered == 95


def test_coverage_report_failed_when_below_target():
    """CoverageReport.passed should be False when coverage < target."""
    report = CoverageReport(
        module="reins.kernel",
        statements=100,
        missed=20,
        coverage_percent=80.0,
        target_percent=90.0,
        passed=False,
    )
    assert report.passed is False
    assert report.covered == 80


def test_check_coverage_gates_all_pass():
    """check_coverage_gates returns (True, []) when all reports pass."""
    reports = [
        CoverageReport("reins.kernel", 100, 5, 95.0, 90.0, True),
        CoverageReport("reins.policy", 80, 4, 95.0, 90.0, True),
    ]
    passed, failures = check_coverage_gates(reports)
    assert passed is True
    assert failures == []


def test_check_coverage_gates_some_fail():
    """check_coverage_gates returns (False, messages) when some reports fail."""
    reports = [
        CoverageReport("reins.kernel", 100, 5, 95.0, 90.0, True),
        CoverageReport("reins.policy", 80, 20, 75.0, 90.0, False),
        CoverageReport("reins.execution", 50, 15, 70.0, 85.0, False),
    ]
    passed, failures = check_coverage_gates(reports)
    assert passed is False
    assert len(failures) == 2
    assert "reins.policy" in failures[0]
    assert "reins.execution" in failures[1]


def test_format_coverage_table_produces_output():
    """format_coverage_table should produce a multi-line ASCII table."""
    reports = [
        CoverageReport("reins.kernel", 200, 10, 95.0, 90.0, True),
        CoverageReport("reins.policy", 100, 20, 80.0, 90.0, False),
    ]
    table = format_coverage_table(reports)
    assert "reins.kernel" in table
    assert "reins.policy" in table
    assert "PASS" in table
    assert "FAIL" in table
    lines = table.strip().split("\n")
    # header + separator + 2 data rows + separator = 5 lines
    assert len(lines) >= 4


def test_parse_coverage_json_handles_missing_file():
    """parse_coverage_json should raise FileNotFoundError for missing file."""
    import pytest

    with pytest.raises(FileNotFoundError):
        parse_coverage_json(Path("/nonexistent/coverage.json"))


def test_parse_coverage_json_parses_valid_data():
    """parse_coverage_json should correctly parse coverage JSON data."""
    coverage_data = {
        "files": {
            "src/reins/kernel/event/envelope.py": {
                "summary": {
                    "num_statements": 50,
                    "missing_lines": 5,
                }
            },
            "src/reins/kernel/reducer/state.py": {
                "summary": {
                    "num_statements": 30,
                    "missing_lines": 2,
                }
            },
            "src/reins/policy/engine.py": {
                "summary": {
                    "num_statements": 40,
                    "missing_lines": 10,
                }
            },
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(coverage_data, f)
        tmp_path = Path(f.name)

    try:
        reports = parse_coverage_json(tmp_path)
        assert len(reports) == len(COVERAGE_TARGETS)

        # Find kernel report
        kernel_report = next(r for r in reports if r.module == "reins.kernel")
        assert kernel_report.statements == 80  # 50 + 30
        assert kernel_report.missed == 7  # 5 + 2
        assert kernel_report.coverage_percent == 91.25

        # Find policy report
        policy_report = next(r for r in reports if r.module == "reins.policy")
        assert policy_report.statements == 40
        assert policy_report.missed == 10
        assert policy_report.coverage_percent == 75.0
        assert policy_report.passed is False
    finally:
        tmp_path.unlink()
