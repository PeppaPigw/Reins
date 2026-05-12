"""Unit tests for API input validation models (SEC-06)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reins.api.models import (
    ApprovalRequest,
    CreateRunRequest,
    ErrorResponse,
    RejectionRequest,
    SubmitCommandRequest,
)


# ---------------------------------------------------------------------------
# CreateRunRequest
# ---------------------------------------------------------------------------


class TestCreateRunRequest:
    def test_valid_data_succeeds(self) -> None:
        req = CreateRunRequest(
            objective="Implement feature X",
            issuer="user",
            constraints=["no network"],
            requested_capabilities=["fs.read"],
        )
        assert req.objective == "Implement feature X"
        assert req.issuer == "user"
        assert req.constraints == ["no network"]
        assert req.requested_capabilities == ["fs.read"]

    def test_empty_objective_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateRunRequest(objective="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("objective",) for e in errors)

    def test_invalid_issuer_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateRunRequest(objective="test", issuer="hacker")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("issuer",) for e in errors)

    def test_objective_exceeding_max_length_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateRunRequest(objective="x" * 10001)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("objective",) for e in errors)

    def test_defaults_applied(self) -> None:
        req = CreateRunRequest(objective="do something")
        assert req.issuer == "user"
        assert req.constraints == []
        assert req.requested_capabilities == []


# ---------------------------------------------------------------------------
# SubmitCommandRequest
# ---------------------------------------------------------------------------


class TestSubmitCommandRequest:
    def test_valid_data_succeeds(self) -> None:
        req = SubmitCommandRequest(
            kind="fs.read",
            args={"path": "/tmp/file.txt"},
            source="model",
        )
        assert req.kind == "fs.read"
        assert req.args == {"path": "/tmp/file.txt"}
        assert req.source == "model"
        assert req.evaluate is False

    def test_empty_kind_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SubmitCommandRequest(kind="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("kind",) for e in errors)

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SubmitCommandRequest(kind="fs.read", source="unknown")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("source",) for e in errors)


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------


class TestApprovalRequest:
    def test_valid_data_succeeds(self) -> None:
        req = ApprovalRequest(request_id="req-123")
        assert req.request_id == "req-123"
        assert req.granted_by == "human"

    def test_empty_request_id_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ApprovalRequest(request_id="")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("request_id",) for e in errors)


# ---------------------------------------------------------------------------
# RejectionRequest
# ---------------------------------------------------------------------------


class TestRejectionRequest:
    def test_valid_data_succeeds(self) -> None:
        req = RejectionRequest(
            request_id="req-456", reason="not allowed"
        )
        assert req.request_id == "req-456"
        assert req.reason == "not allowed"
        assert req.rejected_by == "human"

    def test_reason_exceeding_max_length_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            RejectionRequest(
                request_id="req-1", reason="x" * 2001
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("reason",) for e in errors)


# ---------------------------------------------------------------------------
# ErrorResponse
# ---------------------------------------------------------------------------


class TestErrorResponse:
    def test_serialization_produces_expected_structure(self) -> None:
        resp = ErrorResponse(
            error="Validation failed",
            code="VALIDATION_ERROR",
            details={"errors": [{"loc": ["objective"], "msg": "required"}]},
        )
        data = resp.model_dump()
        assert data["error"] == "Validation failed"
        assert data["code"] == "VALIDATION_ERROR"
        assert "errors" in data["details"]
        assert data["details"]["errors"][0]["loc"] == ["objective"]
