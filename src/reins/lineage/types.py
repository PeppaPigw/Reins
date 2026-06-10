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
    CODE = "code"
    DECISION = "decision"
    TOOL_CALL = "tool_call"
    PROMPT = "prompt"
    RESPONSE = "response"
    FILE_CHANGE = "file_change"
    TEST_RESULT = "test_result"
    APPROVAL = "approval"


class LineageRelation(str, Enum):
    DERIVED_FROM = "derived_from"
    TRIGGERED_BY = "triggered_by"
    APPROVED_BY = "approved_by"
    VALIDATED_BY = "validated_by"
    SUPERSEDES = "supersedes"
    DEPENDS_ON = "depends_on"


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = Field(default_factory=_new_ulid)
    kind: ArtifactKind
    agent_id: str = ""
    run_id: str = ""
    content_hash: str = ""
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class LineageEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(default_factory=_new_ulid)
    source_id: str
    target_id: str
    relation: LineageRelation
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class ProvenanceChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    chain_id: str = Field(default_factory=_new_ulid)
    artifact_id: str
    ancestors: tuple[str, ...] = ()
    depth: int = 0
    complete: bool = True


class LineageQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = ""
    agent_id: str = ""
    run_id: str = ""
    kind: ArtifactKind | None = None
    max_depth: int = 10
    direction: str = "ancestors"


class LineageStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_artifacts: int = 0
    total_edges: int = 0
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_relation: dict[str, int] = Field(default_factory=dict)
    max_chain_depth: int = 0
    orphan_count: int = 0
