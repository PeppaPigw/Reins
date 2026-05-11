"""Integration tests for error recovery: codes, suggestions, and documentation links."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reins.dx.diagnostics import CheckStatus, DiagnosticSuite
from reins.dx.errors import (
    ERROR_CATALOG,
    ErrorCategory,
    ErrorCode,
    ReinsError,
    format_error,
    get_error_code,
    raise_reins_error,
)


class TestErrorMessageQuality:
    """Verify that ReinsError messages include codes, recovery, and docs."""

    def test_reins_error_includes_error_code(self) -> None:
        code = ERROR_CATALOG["REINS-001"]
        error = ReinsError(error_code=code, message="Config not found")
        rendered = str(error)
        assert "REINS-001" in rendered

    def test_reins_error_includes_recovery_suggestion(self) -> None:
        code = ERROR_CATALOG["REINS-003"]
        error = ReinsError(
            error_code=code,
            message="Project not initialized",
            recovery="Run 'reins init' to set up the project",
        )
        rendered = str(error)
        assert "reins init" in rendered
        assert "Recovery:" in rendered

    def test_reins_error_includes_doc_url(self) -> None:
        code = ERROR_CATALOG["REINS-001"]
        error = ReinsError(error_code=code, message="Config missing")
        rendered = str(error)
        assert "https://reins.dev/docs/configuration" in rendered
        assert "Docs:" in rendered

    def test_all_catalog_errors_have_recovery(self) -> None:
        for code_key, error_code in ERROR_CATALOG.items():
            error = ReinsError(
                error_code=error_code,
                message=f"Test error for {code_key}",
                recovery=f"Fix {error_code.title}",
            )
            formatted = format_error(error)
            assert "Recovery:" in formatted, (
                f"{code_key} format_error output missing recovery section"
            )

    def test_error_code_lookup_returns_known_codes(self) -> None:
        for code_key in ERROR_CATALOG:
            result = get_error_code(code_key)
            assert result is not None
            assert result.code == code_key

    def test_error_code_lookup_returns_none_for_unknown(self) -> None:
        result = get_error_code("REINS-999")
        assert result is None


class TestDiagnosticRecovery:
    """Verify that diagnostic checks provide actionable recovery suggestions."""

    def test_missing_init_suggests_reins_init(self, tmp_path: Path) -> None:
        suite = DiagnosticSuite(repo_root=tmp_path)
        result = suite.check_reins_initialized()
        assert result.status == CheckStatus.failed
        assert result.suggestion is not None
        assert "reins init" in result.suggestion

    def test_missing_init_no_root_suggests_reins_init(self) -> None:
        suite = DiagnosticSuite(repo_root=None)
        result = suite.check_reins_initialized()
        assert result.status == CheckStatus.failed
        assert result.suggestion is not None
        assert "reins init" in result.suggestion

    def test_invalid_config_suggests_fix(self, tmp_path: Path) -> None:
        reins_dir = tmp_path / ".reins"
        reins_dir.mkdir()
        config_path = reins_dir / "config.yaml"
        config_path.write_text("invalid: yaml: [broken", encoding="utf-8")
        suite = DiagnosticSuite(repo_root=tmp_path)
        result = suite.check_config_valid()
        assert result.status == CheckStatus.failed
        assert result.suggestion is not None
        assert "YAML" in result.suggestion or "config" in result.suggestion.lower()

    def test_missing_dependency_suggests_install(self) -> None:
        with patch("builtins.__import__", side_effect=_mock_import_missing_structlog):
            suite = DiagnosticSuite()
            result = suite.check_dependencies()
        assert result.status == CheckStatus.failed
        assert result.suggestion is not None
        assert "pip install" in result.suggestion

    def test_passed_check_has_no_suggestion(self, tmp_path: Path) -> None:
        reins_dir = tmp_path / ".reins"
        reins_dir.mkdir()
        suite = DiagnosticSuite(repo_root=tmp_path)
        result = suite.check_reins_initialized()
        assert result.status == CheckStatus.passed
        assert result.suggestion is None


class TestErrorRecoveryFlow:
    """End-to-end: trigger specific errors and verify recovery info."""

    def test_config_not_found_error_has_recovery(self) -> None:
        code = ERROR_CATALOG["REINS-001"]
        error = ReinsError(
            error_code=code,
            message="Config file .reins/config.yaml not found",
            recovery="Create a config file with 'reins init' or copy from template",
        )
        rendered = str(error)
        assert "REINS-001" in rendered
        assert "reins init" in rendered
        assert "https://reins.dev/docs/configuration" in rendered

    def test_not_initialized_error_has_recovery(self) -> None:
        code = ERROR_CATALOG["REINS-003"]
        error = ReinsError(
            error_code=code,
            message="Project is not initialized",
            recovery="Run 'reins init' in your project root",
        )
        rendered = str(error)
        assert "REINS-003" in rendered
        assert "reins init" in rendered
        assert "https://reins.dev/docs/getting-started#init" in rendered

    def test_policy_denied_error_has_recovery(self) -> None:
        code = ERROR_CATALOG["REINS-005"]
        error = ReinsError(
            error_code=code,
            message="Action denied by policy engine",
            recovery="Request approval or adjust policy rules in .reins/policy.yaml",
        )
        rendered = str(error)
        assert "REINS-005" in rendered
        assert "approval" in rendered or "policy" in rendered
        assert "https://reins.dev/docs/policy#denials" in rendered

    def test_integration_auth_error_has_recovery(self) -> None:
        code = ERROR_CATALOG["REINS-006"]
        error = ReinsError(
            error_code=code,
            message="GitHub authentication failed",
            recovery="Set GITHUB_TOKEN environment variable with a valid token",
        )
        rendered = str(error)
        assert "REINS-006" in rendered
        assert "token" in rendered.lower() or "GITHUB_TOKEN" in rendered
        assert "https://reins.dev/docs/integrations#auth" in rendered

    def test_format_error_is_human_readable(self) -> None:
        code = ERROR_CATALOG["REINS-004"]
        error = ReinsError(
            error_code=code,
            message="Journal checksum mismatch at line 42",
            recovery="Run 'reins repair journal' to fix corrupted entries",
            context={"file": ".reins/journal.jsonl", "line": "42"},
        )
        formatted = format_error(error)
        assert "REINS-004" in formatted
        assert "Journal" in formatted
        assert "Recovery:" in formatted
        assert "reins repair" in formatted
        assert "Docs:" in formatted
        assert "Context:" in formatted
        assert "file:" in formatted

    def test_raise_reins_error_raises_with_recovery(self) -> None:
        with pytest.raises(ReinsError) as exc_info:
            raise_reins_error(
                "REINS-003",
                "Not initialized",
                recovery="Run 'reins init'",
                project_dir="/tmp/test",
            )
        error = exc_info.value
        assert error.error_code.code == "REINS-003"
        assert error.recovery == "Run 'reins init'"
        assert error.context["project_dir"] == "/tmp/test"

    def test_raise_reins_error_unknown_code_still_works(self) -> None:
        with pytest.raises(ReinsError) as exc_info:
            raise_reins_error("REINS-999", "Unknown issue", recovery="Contact support")
        error = exc_info.value
        assert error.error_code.code == "REINS-999"
        assert error.recovery == "Contact support"


def _mock_import_missing_structlog(name: str, *args, **kwargs):
    """Mock __import__ that fails for structlog to simulate missing dependency."""
    if name == "structlog":
        raise ImportError(f"No module named '{name}'")
    return original_import(name, *args, **kwargs)


import builtins

original_import = builtins.__import__
