"""Tests for the structured error system."""

from __future__ import annotations

import pytest

from reins.dx.errors import (
    ERROR_CATALOG,
    ErrorCategory,
    ErrorCode,
    ReinsError,
    format_error,
    get_error_code,
    raise_reins_error,
)


def test_error_code_fields():
    """ErrorCode should store all fields correctly."""
    code = ErrorCode(
        code="REINS-001",
        category=ErrorCategory.configuration,
        title="Config file not found",
        doc_url="https://reins.dev/docs/configuration",
    )
    assert code.code == "REINS-001"
    assert code.category == ErrorCategory.configuration
    assert code.title == "Config file not found"
    assert code.doc_url == "https://reins.dev/docs/configuration"


def test_reins_error_has_code_and_message():
    """ReinsError should carry error_code and message."""
    code = ERROR_CATALOG["REINS-003"]
    error = ReinsError(error_code=code, message="Project not initialized")
    assert error.error_code == code
    assert error.message == "Project not initialized"


def test_reins_error_str_includes_code():
    """str(ReinsError) should include the error code."""
    code = ERROR_CATALOG["REINS-001"]
    error = ReinsError(error_code=code, message="File missing")
    text = str(error)
    assert "REINS-001" in text


def test_reins_error_str_includes_recovery():
    """str(ReinsError) should include recovery suggestion when present."""
    code = ERROR_CATALOG["REINS-003"]
    error = ReinsError(
        error_code=code,
        message="Not initialized",
        recovery="Run 'reins init' to set up the project",
    )
    text = str(error)
    assert "Recovery:" in text
    assert "reins init" in text


def test_reins_error_str_includes_doc_url():
    """str(ReinsError) should include doc URL when the error code has one."""
    code = ERROR_CATALOG["REINS-004"]
    error = ReinsError(error_code=code, message="Corrupted journal")
    text = str(error)
    assert "Docs:" in text
    assert "reins.dev" in text


def test_format_error_produces_readable_output():
    """format_error should produce multi-line readable output."""
    code = ERROR_CATALOG["REINS-005"]
    error = ReinsError(
        error_code=code,
        message="Action blocked by policy",
        recovery="Request approval or adjust policy rules",
        context={"action": "file_write", "path": "/etc/passwd"},
    )
    output = format_error(error)
    assert "REINS-005" in output
    assert "Policy denied" in output
    assert "Action blocked by policy" in output
    assert "Recovery:" in output
    assert "Context:" in output
    assert "file_write" in output


def test_error_catalog_has_entries():
    """ERROR_CATALOG should have at least 10 entries."""
    assert len(ERROR_CATALOG) >= 10
    for key, value in ERROR_CATALOG.items():
        assert key == value.code
        assert isinstance(value.category, ErrorCategory)


def test_get_error_code_found():
    """get_error_code should return the ErrorCode for a known code."""
    result = get_error_code("REINS-001")
    assert result is not None
    assert result.code == "REINS-001"
    assert result.category == ErrorCategory.configuration


def test_get_error_code_not_found():
    """get_error_code should return None for an unknown code."""
    result = get_error_code("REINS-999")
    assert result is None


def test_raise_reins_error_raises():
    """raise_reins_error should raise a ReinsError with the correct code."""
    with pytest.raises(ReinsError) as exc_info:
        raise_reins_error(
            "REINS-003",
            "Project not initialized",
            recovery="Run 'reins init'",
        )
    error = exc_info.value
    assert error.error_code.code == "REINS-003"
    assert error.message == "Project not initialized"
    assert error.recovery == "Run 'reins init'"


def test_error_category_enum_values():
    """ErrorCategory should have all expected values."""
    expected = {"configuration", "initialization", "execution", "policy", "integration", "kernel"}
    actual = {member.value for member in ErrorCategory}
    assert expected == actual


def test_reins_error_context_dict():
    """ReinsError should store context dict correctly."""
    code = ERROR_CATALOG["REINS-006"]
    error = ReinsError(
        error_code=code,
        message="Auth failed",
        context={"service": "github", "status": "401"},
    )
    assert error.context == {"service": "github", "status": "401"}
