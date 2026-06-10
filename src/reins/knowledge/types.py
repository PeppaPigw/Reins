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


class NodeKind(str, Enum):
    CONCEPT = "concept"
    ENTITY = "entity"
    ACTION = "action"
    RULE = "rule"
    FACT = "fact"
    SKILL = "skill"
    CONTEXT = "context"
    GOAL = "goal"


class EdgeKind(str, Enum):
    IS_A = "is_a"
    HAS_A = "has_a"
    DEPENDS_ON = "depends_on"
    CAUSES = "causes"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    PRECEDES = "precedes"
    RELATED_TO = "related_to"


class InferenceKind(str, Enum):
    TRANSITIVE = "transitive"
    INHERITANCE = "inheritance"
    CONTRADICTION = "contradiction"
    IMPLICATION = "implication"


class KnowledgeNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(default_factory=_new_ulid)
    kind: NodeKind
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=_utc_now)


class KnowledgeEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(default_factory=_new_ulid)
    source_id: str
    target_id: str
    kind: EdgeKind
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class Inference(BaseModel):
    model_config = ConfigDict(frozen=True)

    inference_id: str = Field(default_factory=_new_ulid)
    kind: InferenceKind
    source_node_id: str
    target_node_id: str
    via_path: tuple[str, ...] = ()
    confidence: float = 0.0
    explanation: str = ""


class QueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: tuple[KnowledgeNode, ...] = ()
    edges: tuple[KnowledgeEdge, ...] = ()
    inferences: tuple[Inference, ...] = ()


class KnowledgeGraphStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_nodes: int = 0
    total_edges: int = 0
    node_kinds: dict[str, int] = Field(default_factory=dict)
    edge_kinds: dict[str, int] = Field(default_factory=dict)
    avg_connections: float = 0.0
    connected_components: int = 0
