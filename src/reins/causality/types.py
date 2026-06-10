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


class CausalRelation(str, Enum):
    CAUSES = "causes"
    ENABLES = "enables"
    PREVENTS = "prevents"
    CORRELATES = "correlates"
    INHIBITS = "inhibits"


class NodeKind(str, Enum):
    ACTION = "action"
    OUTCOME = "outcome"
    STATE = "state"
    EVENT = "event"
    DECISION = "decision"


class ConfidenceLevel(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHETICAL = "hypothetical"


class CausalNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(default_factory=_new_ulid)
    kind: NodeKind
    label: str
    description: str = ""
    agent_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)


class CausalEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(default_factory=_new_ulid)
    source_id: str
    target_id: str
    relation: CausalRelation
    strength: float = 1.0
    confidence: ConfidenceLevel = ConfidenceLevel.OBSERVED
    evidence_count: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class CausalChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    chain_id: str = Field(default_factory=_new_ulid)
    nodes: tuple[str, ...] = ()
    edges: tuple[str, ...] = ()
    total_strength: float = 0.0
    weakest_link: float = 0.0


class Counterfactual(BaseModel):
    model_config = ConfigDict(frozen=True)

    counterfactual_id: str = Field(default_factory=_new_ulid)
    intervention_node: str
    target_node: str
    original_outcome: str = ""
    predicted_outcome: str = ""
    confidence: float = 0.0
    causal_paths: tuple[CausalChain, ...] = ()


class RootCauseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_node: str
    root_causes: tuple[str, ...] = ()
    chains: tuple[CausalChain, ...] = ()
    confidence: float = 0.0


class CausalGraphStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_nodes: int = 0
    total_edges: int = 0
    avg_strength: float = 0.0
    max_depth: int = 0
    connected_components: int = 0
