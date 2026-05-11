"""Structured error system with error codes, recovery suggestions, and doc URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import NoReturn


class ErrorCategory(str, Enum):
    configuration = "configuration"
    initialization = "initialization"
    execution = "execution"
    policy = "policy"
    integration = "integration"
    kernel = "kernel"


@dataclass(frozen=True)
class ErrorCode:
    """Identifies a specific error type with metadata."""

    code: str
    category: ErrorCategory
    title: str
    doc_url: str | None = None


class ReinsError(Exception):
    """Structured error with code, recovery suggestion, and documentation link."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        recovery: str | None = None,
        context: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.recovery = recovery
        self.context: dict[str, str] = context or {}

    def __str__(self) -> str:
        parts = [f"[{self.error_code.code}] {self.message}"]
        if self.recovery:
            parts.append(f"  Recovery: {self.recovery}")
        if self.error_code.doc_url:
            parts.append(f"  Docs: {self.error_code.doc_url}")
        return "\n".join(parts)


ERROR_CATALOG: dict[str, ErrorCode] = {
    "REINS-001": ErrorCode(
        code="REINS-001",
        category=ErrorCategory.configuration,
        title="Config file not found",
        doc_url="https://reins.dev/docs/configuration",
    ),
    "REINS-002": ErrorCode(
        code="REINS-002",
        category=ErrorCategory.configuration,
        title="Invalid config format",
        doc_url="https://reins.dev/docs/configuration#format",
    ),
    "REINS-003": ErrorCode(
        code="REINS-003",
        category=ErrorCategory.initialization,
        title="Not initialized",
        doc_url="https://reins.dev/docs/getting-started#init",
    ),
    "REINS-004": ErrorCode(
        code="REINS-004",
        category=ErrorCategory.kernel,
        title="Journal corrupted",
        doc_url="https://reins.dev/docs/troubleshooting#journal",
    ),
    "REINS-005": ErrorCode(
        code="REINS-005",
        category=ErrorCategory.policy,
        title="Policy denied",
        doc_url="https://reins.dev/docs/policy#denials",
    ),
    "REINS-006": ErrorCode(
        code="REINS-006",
        category=ErrorCategory.integration,
        title="Integration auth failed",
        doc_url="https://reins.dev/docs/integrations#auth",
    ),
    "REINS-007": ErrorCode(
        code="REINS-007",
        category=ErrorCategory.configuration,
        title="Platform not supported",
        doc_url="https://reins.dev/docs/platforms",
    ),
    "REINS-008": ErrorCode(
        code="REINS-008",
        category=ErrorCategory.execution,
        title="Migration failed",
        doc_url="https://reins.dev/docs/migrations",
    ),
    "REINS-009": ErrorCode(
        code="REINS-009",
        category=ErrorCategory.execution,
        title="Task not found",
        doc_url="https://reins.dev/docs/tasks",
    ),
    "REINS-010": ErrorCode(
        code="REINS-010",
        category=ErrorCategory.initialization,
        title="Dependency missing",
        doc_url="https://reins.dev/docs/setup#dependencies",
    ),
}


def format_error(error: ReinsError) -> str:
    """Render a ReinsError as terminal-friendly output."""
    lines = [
        f"Error [{error.error_code.code}]: {error.error_code.title}",
        f"  {error.message}",
    ]
    if error.recovery:
        lines.append(f"  Recovery: {error.recovery}")
    if error.error_code.doc_url:
        lines.append(f"  Docs: {error.error_code.doc_url}")
    if error.context:
        lines.append("  Context:")
        for key, value in error.context.items():
            lines.append(f"    {key}: {value}")
    return "\n".join(lines)


def get_error_code(code: str) -> ErrorCode | None:
    """Look up an error code in the catalog."""
    return ERROR_CATALOG.get(code)


def raise_reins_error(
    code: str, message: str, recovery: str | None = None, **context: str
) -> NoReturn:
    """Convenience: look up code in catalog, create ReinsError, and raise it."""
    error_code = ERROR_CATALOG.get(code)
    if error_code is None:
        error_code = ErrorCode(
            code=code,
            category=ErrorCategory.execution,
            title="Unknown error",
        )
    raise ReinsError(
        error_code=error_code,
        message=message,
        recovery=recovery,
        context=context if context else None,
    )
