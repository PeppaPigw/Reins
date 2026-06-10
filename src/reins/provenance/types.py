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


class ArtifactKind(str, Enum):
    DATA = "data"
    MODEL = "model"
    DECISION = "decision"
    CODE = "code"
    CONFIG = "config"
    PROMPT = "prompt"
    OUTPUT = "output"
    INTERMEDIATE = "intermediate"


class TransformKind(str, Enum):
    CREATION = "creation"
    DERIVATION = "derivation"
    AGGREGATION = "aggregation"
    FILTERING = "filtering"
    ENRICHMENT = "enrichment"
    VALIDATION = "validation"
    APPROVAL = "approval"


class IntegrityStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    TAMPERED = "tampered"
    EXPIRED = "expired"
    MISSING = "missing"


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: ArtifactKind = ArtifactKind.DATA
    checksum: str = ""
    creator_id: str = ""
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class Transform(BaseModel):
    model_config = ConfigDict(frozen=True)

    transform_id: str = Field(default_factory=_new_ulid)
    kind: TransformKind
    agent_id: str
    input_ids: tuple[str, ...] = ()
    output_ids: tuple[str, ...] = ()
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    performed_at: datetime = Field(default_factory=_utc_now)


class ProvenanceChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    chain_id: str = Field(default_factory=_new_ulid)
    artifact_id: str
    transforms: tuple[str, ...] = ()
    origin_artifact_ids: tuple[str, ...] = ()
    depth: int = 0
    integrity: IntegrityStatus = IntegrityStatus.UNVERIFIED


class ProvenanceStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_artifacts: int = 0
    total_transforms: int = 0
    avg_chain_depth: float = 0.0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_integrity: dict[str, int] = Field(default_factory=dict)
    agents_involved: int = 0
