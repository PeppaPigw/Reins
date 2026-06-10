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
    AGENT = "agent"
    SERVICE = "service"
    GATEWAY = "gateway"
    BROKER = "broker"
    STORAGE = "storage"


class EdgeKind(str, Enum):
    DIRECT = "direct"
    RELAY = "relay"
    BROADCAST = "broadcast"
    SUBSCRIBE = "subscribe"
    BIDIRECTIONAL = "bidirectional"


class TopologyHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    PARTITIONED = "partitioned"
    DISCONNECTED = "disconnected"


class TopologyNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    kind: NodeKind = NodeKind.AGENT
    label: str = ""
    capacity: int = 10
    load: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopologyEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(default_factory=_new_ulid)
    source: str
    target: str
    kind: EdgeKind = EdgeKind.DIRECT
    weight: float = 1.0
    latency_ms: float = 0.0
    bandwidth: float = 1.0


class Partition(BaseModel):
    model_config = ConfigDict(frozen=True)

    partition_id: str = Field(default_factory=_new_ulid)
    nodes: tuple[str, ...] = ()
    is_isolated: bool = False


class Route(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    path: tuple[str, ...] = ()
    total_weight: float = 0.0
    hops: int = 0


class Bottleneck(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    degree: int = 0
    betweenness: float = 0.0
    load_ratio: float = 0.0


class TopologyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_nodes: int = 0
    total_edges: int = 0
    partitions: int = 0
    avg_degree: float = 0.0
    density: float = 0.0
    health: TopologyHealth = TopologyHealth.HEALTHY
    by_node_kind: dict[str, int] = Field(default_factory=dict)
    by_edge_kind: dict[str, int] = Field(default_factory=dict)
