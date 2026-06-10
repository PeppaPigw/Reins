from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class NegotiationOutcome(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    PARTIAL = "partial"
    QUEUED = "queued"


class CompositionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    FALLBACK = "fallback"
    BEST_OF = "best_of"


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability_id: str = Field(default_factory=_new_ulid)
    name: str
    version: str = "1.0"
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    cost_per_call: float = 0.0
    avg_latency_ms: float = 0.0
    max_concurrency: int = 1
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityProvider(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    capabilities: tuple[Capability, ...] = ()
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    priority: int = 0
    registered_at: datetime = Field(default_factory=_utc_now)


class CapabilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=_new_ulid)
    requester_id: str
    capability_name: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    max_cost: float | None = None
    max_latency_ms: float | None = None
    preferred_providers: tuple[str, ...] = ()
    requested_at: datetime = Field(default_factory=_utc_now)


class NegotiationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    request_id: str
    outcome: NegotiationOutcome
    provider_id: str | None = None
    capability_id: str | None = None
    reason: str = ""
    negotiated_at: datetime = Field(default_factory=_utc_now)


class ComposedCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    composition_id: str = Field(default_factory=_new_ulid)
    name: str
    mode: CompositionMode
    steps: tuple[str, ...] = ()
    fallback_order: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)


class InvocationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    invocation_id: str = Field(default_factory=_new_ulid)
    capability_name: str
    provider_id: str
    success: bool
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    cost: float = 0.0
    invoked_at: datetime = Field(default_factory=_utc_now)
