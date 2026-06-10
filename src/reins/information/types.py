from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InformationMetric(str, Enum):
    ENTROPY = "entropy"
    MUTUAL_INFORMATION = "mutual_information"
    KL_DIVERGENCE = "kl_divergence"
    CROSS_ENTROPY = "cross_entropy"
    INFORMATION_GAIN = "information_gain"
    REDUNDANCY = "redundancy"


class CompressionStrategy(str, Enum):
    MAX_ENTROPY = "max_entropy"
    MIN_REDUNDANCY = "min_redundancy"
    MAX_RELEVANCE = "max_relevance"
    MRMR = "mrmr"
    INFORMATION_BOTTLENECK = "information_bottleneck"


class ContextItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str = Field(default_factory=_new_ulid)
    content: str
    tokens: int = 0
    relevance: float = 0.5
    entropy: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class InformationProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(default_factory=_new_ulid)
    total_entropy: float = 0.0
    avg_relevance: float = 0.0
    redundancy_ratio: float = 0.0
    information_density: float = 0.0
    effective_tokens: int = 0
    total_tokens: int = 0


class ContextSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    selection_id: str = Field(default_factory=_new_ulid)
    selected_ids: tuple[str, ...] = ()
    strategy: CompressionStrategy = CompressionStrategy.MRMR
    total_tokens: int = 0
    information_retained: float = 0.0
    compression_ratio: float = 1.0
    selected_at: datetime = Field(default_factory=_utc_now)


class InformationStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_items: int = 0
    total_selections: int = 0
    avg_compression_ratio: float = 1.0
    avg_information_retained: float = 1.0
    by_strategy: dict[str, int] = Field(default_factory=dict)
