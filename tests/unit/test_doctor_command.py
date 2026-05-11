"""Tests for the doctor command and diagnostic suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.dx.diagnostics import CheckStatus, DiagnosticResult, DiagnosticSuite


def test_check_python_version_passes():
    """Python version check should pass on the current interpreter (>= 3.11)."""
    suite = DiagnosticSuite()
    result = suite.check_python_version()
    assert result.status == CheckStatus.passed
    assert "3.1" in result.message or "3.2" in result.message


def test_check_git_available_passes():
    """Git availability check should pass in a dev environment."""
    suite = DiagnosticSuite()
    result = suite.check_git_available()
    assert result.status == CheckStatus.passed
    assert "git" in result.message.lower()


def test_check_reins_initialized_passes(tmp_path: Path):
    """Should pass when .reins directory exists."""
    (tmp_path / ".reins").mkdir()
    suite = DiagnosticSuite(repo_root=tmp_path)
    result = suite.check_reins_initialized()
    assert result.status == CheckStatus.passed


def test_check_reins_initialized_fails_when_missing(tmp_path: Path):
    """Should fail when .reins directory does not exist."""
    suite = DiagnosticSuite(repo_root=tmp_path)
    result = suite.check_reins_initialized()
    assert result.status == CheckStatus.failed
    assert result.suggestion is not None
    assert "reins init" in result.suggestion


def test_check_reins_initialized_fails_when_no_root():
    """Should fail when repo_root is None."""
    suite = DiagnosticSuite(repo_root=None)
    result = suite.check_reins_initialized()
    assert result.status == CheckStatus.failed


def test_check_dependencies_passes():
    """Dependencies check should pass in a properly installed environment."""
    suite = DiagnosticSuite()
    result = suite.check_dependencies()
    assert result.status == CheckStatus.passed


def test_check_config_valid_passes(tmp_path: Path):
    """Should pass when config.yaml is valid YAML."""
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir()
    config_file = reins_dir / "config.yaml"
    config_file.write_text("platform: claude\nproject_type: backend\n", encoding="utf-8")
    suite = DiagnosticSuite(repo_root=tmp_path)
    result = suite.check_config_valid()
    assert result.status == CheckStatus.passed


def test_check_config_valid_fails_invalid_yaml(tmp_path: Path):
    """Should fail when config.yaml has invalid YAML syntax."""
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir()
    config_file = reins_dir / "config.yaml"
    config_file.write_text("invalid: yaml: [unclosed", encoding="utf-8")
    suite = DiagnosticSuite(repo_root=tmp_path)
    result = suite.check_config_valid()
    assert result.status == CheckStatus.failed
    assert result.suggestion is not None


def test_run_all_returns_results(tmp_path: Path):
    """run_all should return a list of DiagnosticResult objects."""
    (tmp_path / ".reins").mkdir()
    suite = DiagnosticSuite(repo_root=tmp_path)
    results = suite.run_all()
    assert len(results) >= 7
    assert all(isinstance(r, DiagnosticResult) for r in results)


def test_format_results_includes_status():
    """format_results should include status indicators in output."""
    suite = DiagnosticSuite()
    results = [
        DiagnosticResult(
            name="test_check",
            status=CheckStatus.passed,
            message="All good",
        ),
        DiagnosticResult(
            name="failing_check",
            status=CheckStatus.failed,
            message="Something wrong",
            suggestion="Fix it",
        ),
    ]
    output = suite.format_results(results)
    assert "PASS" in output
    assert "FAIL" in output
    assert "Fix it" in output


def test_diagnostic_result_fields():
    """DiagnosticResult should store all fields correctly."""
    result = DiagnosticResult(
        name="my_check",
        status=CheckStatus.warning,
        message="Something is off",
        suggestion="Try this fix",
        doc_url="https://reins.dev/docs/fix",
    )
    assert result.name == "my_check"
    assert result.status == CheckStatus.warning
    assert result.message == "Something is off"
    assert result.suggestion == "Try this fix"
    assert result.doc_url == "https://reins.dev/docs/fix"


def test_doctor_command_registered_in_app():
    """The doctor command should be registered in the typer app."""
    from reins.cli.main import app

    command_names = [cmd.name for cmd in app.registered_commands]
    assert "doctor" in command_names
