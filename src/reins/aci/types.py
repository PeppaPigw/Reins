from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

import ulid
from pydantic import BaseModel, ConfigDict, Field, field_validator


def new_ulid() -> str:
    return str(ulid.new())


def normalize_tuple(value: Iterable[object] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(str(item) for item in value if str(item))


class CommandCategory(str, Enum):
    NAVIGATION = "navigation"
    EDITING = "editing"
    EXECUTION = "execution"
    SEARCH = "search"
    CONTEXT = "context"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ACIModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SearchResult(ACIModel):
    path: str = Field(..., min_length=1)
    line: int = Field(default=1, ge=1)
    column: int | None = Field(default=None, ge=1)
    snippet: str = ""
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    symbol: str | None = None


class Diagnostic(ACIModel):
    message: str = Field(..., min_length=1)
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    code: str | None = None
    suggestion: str | None = None


class EditResult(ACIModel):
    file: str = Field(..., min_length=1)
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    lines_added: int = Field(default=0, ge=0)
    lines_removed: int = Field(default=0, ge=0)
    diff: str = ""


class NavigationResult(ACIModel):
    file: str = Field(..., min_length=1)
    line: int = Field(default=1, ge=1)
    column: int | None = Field(default=None, ge=1)
    preview: str = ""


class CommandContext(ACIModel):
    """Current agent context for command execution."""

    working_directory: str
    current_file: str | None = None
    cursor_line: int | None = Field(default=None, ge=1)
    open_files: tuple[str, ...] = Field(default_factory=tuple)
    recent_commands: tuple[str, ...] = Field(default_factory=tuple)
    active_task: str | None = None
    search_results: tuple[SearchResult, ...] | None = None

    @field_validator("open_files", "recent_commands", mode="before")
    @classmethod
    def _validate_tuple(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_tuple(value)


class ContextUpdate(ACIModel):
    """How context changed after a command."""

    new_file: str | None = None
    new_cursor_line: int | None = Field(default=None, ge=1)
    files_modified: tuple[str, ...] = Field(default_factory=tuple)
    files_created: tuple[str, ...] = Field(default_factory=tuple)
    diagnostics_added: int = Field(default=0, ge=0)
    diagnostics_resolved: int = Field(default=0, ge=0)

    @field_validator("files_modified", "files_created", mode="before")
    @classmethod
    def _validate_tuple(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_tuple(value)


class ACICommand(ACIModel):
    """A structured command in the Agent-Computer Interface."""

    command_id: str = Field(default_factory=new_ulid, min_length=1)
    name: str = Field(..., min_length=1)
    category: CommandCategory
    args: dict[str, Any] = Field(default_factory=dict)
    context: CommandContext


class ACIResponse(ACIModel):
    """Structured response from an ACI command."""

    command_id: str = Field(..., min_length=1)
    success: bool
    output: str
    context_update: ContextUpdate | None = None
    suggestions: tuple[str, ...] = Field(default_factory=tuple)
    diagnostics: tuple[Diagnostic, ...] = Field(default_factory=tuple)

    @field_validator("suggestions", mode="before")
    @classmethod
    def _validate_suggestions(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return normalize_tuple(value)

    @field_validator("diagnostics", mode="before")
    @classmethod
    def _validate_diagnostics(
        cls,
        value: Iterable[Diagnostic | dict[str, Any]] | None,
    ) -> tuple[Diagnostic, ...]:
        if value is None:
            return ()
        return tuple(
            item if isinstance(item, Diagnostic) else Diagnostic.model_validate(item)
            for item in value
        )
