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


class ModelProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    MISTRAL = "mistral"
    COHERE = "cohere"
    LOCAL = "local"
    XAI = "xai"


class ModelCapability(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    REASONING = "reasoning"
    PLANNING = "planning"
    TOOL_USE = "tool_use"
    LONG_CONTEXT = "long_context"
    FAST_RESPONSE = "fast_response"
    VISION = "vision"
    STRUCTURED_OUTPUT = "structured_output"
    MULTILINGUAL = "multilingual"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RoutingStrategy(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    BEST_QUALITY = "best_quality"
    BALANCED = "balanced"
    CAPABILITY_MATCH = "capability_match"
    FALLBACK_CHAIN = "fallback_chain"


class CostPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_cost_per_request: float = 1.0
    max_cost_per_hour: float = 20.0
    max_cost_per_day: float = 100.0
    prefer_cached: bool = True
    allow_fallback_on_budget: bool = True


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    provider: ModelProvider
    display_name: str
    capabilities: tuple[ModelCapability, ...] = ()
    max_context_tokens: int = 128_000
    max_output_tokens: int = 4_096
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0
    avg_latency_ms: float = 1000.0
    quality_score: float = 0.8
    supports_streaming: bool = True
    supports_tool_use: bool = True
    rate_limit_rpm: int = 60
    is_available: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    selected_model: ModelConfig
    strategy_used: RoutingStrategy
    reason: str
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    fallback_models: tuple[ModelConfig, ...] = ()
    decided_at: datetime = Field(default_factory=_utc_now)


class UsageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(default_factory=_new_ulid)
    model_id: str
    provider: ModelProvider
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    timestamp: datetime = Field(default_factory=_utc_now)


class ModelRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    models: tuple[ModelConfig, ...] = ()
    default_strategy: RoutingStrategy = RoutingStrategy.BALANCED
    cost_policy: CostPolicy = Field(default_factory=CostPolicy)
