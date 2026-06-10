from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Iterable, TypeVar

import ulid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_ulid() -> str:
    return str(ulid.new())


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


T = TypeVar("T", bound=BaseModel)


def normalize_model_tuple(
    value: Iterable[T | dict[str, Any]] | None,
    model_type: type[T],
) -> tuple[T, ...]:
    if value is None:
        return ()
    return tuple(
        item if isinstance(item, model_type) else model_type.model_validate(item)
        for item in value
    )


class PredicateType(str, Enum):
    FILE_EXISTS = "file_exists"
    TEST_PASSES = "test_passes"
    PATTERN_MATCHES = "pattern_matches"
    METRIC_THRESHOLD = "metric_threshold"
    CUSTOM_FUNCTION = "custom_function"
    INVARIANT_HOLDS = "invariant_holds"


class GuardType(str, Enum):
    TEST_SUITE = "test_suite"
    METRIC_FLOOR = "metric_floor"
    FILE_UNCHANGED = "file_unchanged"
    API_CONTRACT = "api_contract"


class QualityLevel(str, Enum):
    PRE_COMMIT = "pre_commit"
    PRE_MERGE = "pre_merge"
    RELEASE = "release"
    REGRESSION = "regression"


class OutcomeModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class VerificationPredicate(OutcomeModel):
    """A single verifiable condition that must hold."""

    predicate_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    predicate_type: PredicateType
    target: str = Field(..., min_length=1)
    expected: Any
    weight: float = Field(..., ge=0.0, le=1.0)
    required: bool = False


class RegressionGuard(OutcomeModel):
    """Ensures existing behavior is preserved."""

    guard_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    guard_type: GuardType
    baseline: Any
    tolerance: float = Field(default=0.0, ge=0.0)


class PredicateResult(OutcomeModel):
    result_id: str = Field(default_factory=new_ulid, min_length=1)
    predicate_id: str = Field(..., min_length=1)
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    weight: float = Field(..., ge=0.0, le=1.0)
    required: bool
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def _validate_evaluated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class RegressionResult(OutcomeModel):
    result_id: str = Field(default_factory=new_ulid, min_length=1)
    guard_id: str = Field(..., min_length=1)
    guard_type: GuardType
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    baseline: Any = None
    observed: Any = None
    deviation: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def _validate_evaluated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class OutcomeSpec(OutcomeModel):
    """Formal specification of what 'done' means for a task."""

    outcome_id: str = Field(..., min_length=1)
    task_id: str = Field(..., min_length=1)
    predicates: tuple[VerificationPredicate, ...] = Field(..., min_length=1)
    acceptance_threshold: float = Field(..., ge=0.0, le=1.0)
    regression_guards: tuple[RegressionGuard, ...] = Field(default_factory=tuple)
    partial_credit: bool = True
    deadline: datetime | None = None

    @field_validator("predicates", mode="before")
    @classmethod
    def _validate_predicates(
        cls,
        value: Iterable[VerificationPredicate | dict[str, Any]] | None,
    ) -> tuple[VerificationPredicate, ...]:
        return normalize_model_tuple(value, VerificationPredicate)

    @field_validator("regression_guards", mode="before")
    @classmethod
    def _validate_regression_guards(
        cls,
        value: Iterable[RegressionGuard | dict[str, Any]] | None,
    ) -> tuple[RegressionGuard, ...]:
        return normalize_model_tuple(value, RegressionGuard)

    @field_validator("deadline", mode="before")
    @classmethod
    def _validate_deadline(cls, value: datetime | str | None) -> datetime | None:
        return normalize_datetime(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_ids_and_weights(self) -> OutcomeSpec:
        predicate_ids = [predicate.predicate_id for predicate in self.predicates]
        if len(predicate_ids) != len(set(predicate_ids)):
            raise ValueError("predicate_id values must be unique within an outcome")
        guard_ids = [guard.guard_id for guard in self.regression_guards]
        if len(guard_ids) != len(set(guard_ids)):
            raise ValueError("guard_id values must be unique within an outcome")
        if sum(predicate.weight for predicate in self.predicates) <= 0.0:
            raise ValueError("at least one predicate must have a positive weight")
        return self


class OutcomeResult(OutcomeModel):
    """Result of evaluating an outcome specification."""

    result_id: str = Field(default_factory=new_ulid, min_length=1)
    outcome_id: str = Field(..., min_length=1)
    overall_score: float = Field(..., ge=0.0, le=1.0)
    passed: bool
    predicate_results: tuple[PredicateResult, ...] = Field(default_factory=tuple)
    regression_results: tuple[RegressionResult, ...] = Field(default_factory=tuple)
    partial_progress: float = Field(..., ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("predicate_results", mode="before")
    @classmethod
    def _validate_predicate_results(
        cls,
        value: Iterable[PredicateResult | dict[str, Any]] | None,
    ) -> tuple[PredicateResult, ...]:
        return normalize_model_tuple(value, PredicateResult)

    @field_validator("regression_results", mode="before")
    @classmethod
    def _validate_regression_results(
        cls,
        value: Iterable[RegressionResult | dict[str, Any]] | None,
    ) -> tuple[RegressionResult, ...]:
        return normalize_model_tuple(value, RegressionResult)

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def _validate_evaluated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class QualityGate(OutcomeModel):
    gate_id: str = Field(default_factory=new_ulid, min_length=1)
    name: str = Field(..., min_length=1)
    outcomes: tuple[OutcomeSpec, ...] = Field(..., min_length=1)
    min_score: float = Field(..., ge=0.0, le=1.0)
    blocking: bool = True
    quality_level: QualityLevel = QualityLevel.PRE_MERGE

    @field_validator("outcomes", mode="before")
    @classmethod
    def _validate_outcomes(
        cls,
        value: Iterable[OutcomeSpec | dict[str, Any]] | None,
    ) -> tuple[OutcomeSpec, ...]:
        return normalize_model_tuple(value, OutcomeSpec)


class GateResult(OutcomeModel):
    result_id: str = Field(default_factory=new_ulid, min_length=1)
    gate_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    quality_level: QualityLevel
    passed: bool
    blocking: bool
    overall_score: float = Field(..., ge=0.0, le=1.0)
    min_score: float = Field(..., ge=0.0, le=1.0)
    outcome_results: tuple[OutcomeResult, ...] = Field(default_factory=tuple)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("outcome_results", mode="before")
    @classmethod
    def _validate_outcome_results(
        cls,
        value: Iterable[OutcomeResult | dict[str, Any]] | None,
    ) -> tuple[OutcomeResult, ...]:
        return normalize_model_tuple(value, OutcomeResult)

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def _validate_evaluated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class PipelineGateResult(OutcomeModel):
    result_id: str = Field(default_factory=new_ulid, min_length=1)
    passed: bool
    overall_score: float = Field(..., ge=0.0, le=1.0)
    gate_results: tuple[GateResult, ...] = Field(default_factory=tuple)
    blocked_by: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)

    @field_validator("gate_results", mode="before")
    @classmethod
    def _validate_gate_results(
        cls,
        value: Iterable[GateResult | dict[str, Any]] | None,
    ) -> tuple[GateResult, ...]:
        return normalize_model_tuple(value, GateResult)

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def _validate_evaluated_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)


class RegressionAlert(OutcomeModel):
    alert_id: str = Field(default_factory=new_ulid, min_length=1)
    outcome_id: str = Field(..., min_length=1)
    previous_score: float = Field(..., ge=0.0, le=1.0)
    current_score: float = Field(..., ge=0.0, le=1.0)
    delta: float
    threshold: float = Field(..., ge=0.0, le=1.0)
    previous_result_id: str | None = None
    current_result_id: str | None = None
    detected_at: datetime = Field(default_factory=utc_now)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("detected_at", mode="before")
    @classmethod
    def _validate_detected_at(cls, value: datetime | str) -> datetime:
        return normalize_datetime(value)
