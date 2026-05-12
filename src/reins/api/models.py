"""Pydantic v2 request/response models for the Reins REST API.

Provides input validation for all API endpoints, ensuring malformed
payloads produce structured 422 errors instead of crashes (SEC-06).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

_VALID_ISSUERS = {"user", "scheduler", "webhook", "remote_agent"}
_VALID_SOURCES = {"model", "human", "hook", "skill"}


class CreateRunRequest(BaseModel):
    """Validated payload for POST /runs."""

    objective: str = Field(..., min_length=1, max_length=10000)
    issuer: str = Field(default="user")
    constraints: list[str] = Field(default_factory=list, max_length=50)
    requested_capabilities: list[str] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("issuer")
    @classmethod
    def issuer_must_be_known(cls, v: str) -> str:
        if v not in _VALID_ISSUERS:
            raise ValueError(
                f"issuer must be one of {sorted(_VALID_ISSUERS)}, got {v!r}"
            )
        return v


class SubmitCommandRequest(BaseModel):
    """Validated payload for POST /runs/{id}/commands."""

    kind: str = Field(..., min_length=1, max_length=200)
    args: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="model")
    rationale_ref: str | None = None
    idempotency_key: str | None = None
    evaluate: bool = False

    @field_validator("source")
    @classmethod
    def source_must_be_known(cls, v: str) -> str:
        if v not in _VALID_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(_VALID_SOURCES)}, got {v!r}"
            )
        return v


class ApprovalRequest(BaseModel):
    """Validated payload for POST /runs/{id}/approve."""

    request_id: str = Field(..., min_length=1)
    granted_by: str = Field(
        default="human", min_length=1, max_length=200
    )


class RejectionRequest(BaseModel):
    """Validated payload for POST /runs/{id}/reject."""

    request_id: str = Field(..., min_length=1)
    reason: str = Field(default="rejected by human", max_length=2000)
    rejected_by: str = Field(
        default="human", min_length=1, max_length=200
    )


class ErrorResponse(BaseModel):
    """Structured error response body."""

    error: str
    code: str = "VALIDATION_ERROR"
    details: dict[str, Any] | None = None
