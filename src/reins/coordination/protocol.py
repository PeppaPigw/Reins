from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable
from urllib.parse import urlparse

import ulid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reins.intelligence.types import TrustLevel

if TYPE_CHECKING:
    from reins.coordination.registry import NodeRegistry
    from reins.coordination.router import TaskRouter


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _normalize_unique(value: Iterable[object] | None, *, sort: bool) -> tuple[str, ...]:
    if value is None:
        return ()
    items = [str(item).strip() for item in value if str(item).strip()]
    unique = tuple(dict.fromkeys(items))
    return tuple(sorted(unique)) if sort else unique


class NodeStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"


class MessageType(str, Enum):
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    TASK_ASSIGN = "task_assign"
    TASK_COMPLETE = "task_complete"
    TASK_FAIL = "task_fail"
    CAPABILITY_QUERY = "capability_query"
    CAPABILITY_RESPONSE = "capability_response"
    CONFLICT_RESOLUTION = "conflict_resolution"
    CONSENSUS_REQUEST = "consensus_request"
    CONSENSUS_VOTE = "consensus_vote"


class RiskTier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class AssignmentStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    FAILED = "failed"
    REASSIGNED = "reassigned"


class ResolutionStrategy(str, Enum):
    LAST_WRITER_WINS = "last_writer_wins"
    MERGE = "merge"
    MANUAL = "manual"
    CONSENSUS = "consensus"


class RoutingStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CAPABILITY_MATCH = "capability_match"
    TRUST_WEIGHTED = "trust_weighted"
    AFFINITY = "affinity"


class AgentNode(BaseModel):
    """Remote agent node known to the distributed coordinator."""

    model_config = ConfigDict(frozen=True)

    node_id: str = Field(default_factory=_new_ulid, min_length=1)
    endpoint: str = Field(..., min_length=1)
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    status: NodeStatus = NodeStatus.IDLE
    last_heartbeat: datetime = Field(default_factory=_utc_now)
    current_task_id: str | None = None
    trust_level: TrustLevel = TrustLevel.semi_auto
    max_concurrent_tasks: int = Field(default=1, ge=1)
    current_load: int = Field(default=0, ge=0)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    completed_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(default=0, ge=0)
    registered_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.scheme:
            raise ValueError("endpoint must be a URL with a scheme")
        if parsed.scheme in {"http", "https", "ws", "wss"} and not parsed.netloc:
            raise ValueError("network endpoint URLs must include a host")
        return value

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value, sort=True)

    @field_validator("last_heartbeat", "registered_at", mode="before")
    @classmethod
    def _validate_datetime(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_load(self) -> AgentNode:
        if self.current_load > self.max_concurrent_tasks:
            raise ValueError("current_load cannot exceed max_concurrent_tasks")
        if self.status is NodeStatus.IDLE and self.current_load > 0:
            raise ValueError("idle nodes cannot have active load")
        return self

    @property
    def load_ratio(self) -> float:
        return self.current_load / self.max_concurrent_tasks

    @property
    def success_rate(self) -> float:
        total = self.completed_tasks + self.failed_tasks
        return 0.5 if total == 0 else self.completed_tasks / total

    @property
    def is_routable(self) -> bool:
        return (
            self.status in {NodeStatus.IDLE, NodeStatus.BUSY}
            and self.current_load < self.max_concurrent_tasks
        )


class CoordinationMessage(BaseModel):
    """Wire protocol message with canonical SHA-256 integrity checksum."""

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=_new_ulid, min_length=1)
    source_node_id: str = Field(..., min_length=1)
    target_node_id: str | None = None
    broadcast: bool = False
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    checksum: str = ""

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_target_and_checksum(self) -> CoordinationMessage:
        if self.target_node_id is None and not self.broadcast:
            raise ValueError("target_node_id is required unless broadcast is true")
        if self.target_node_id is not None and self.broadcast:
            raise ValueError("broadcast messages cannot also target a single node")
        if not self.checksum:
            object.__setattr__(self, "checksum", self.compute_checksum())
        return self

    def checksum_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"checksum"})

    def compute_checksum(self) -> str:
        payload = json.dumps(
            self.checksum_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify_checksum(self) -> bool:
        return self.checksum == self.compute_checksum()


class TaskAssignment(BaseModel):
    """Distributed task routing request and assignment state."""

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    risk_tier: RiskTier = RiskTier.T1
    deadline: datetime | None = None
    priority: int = Field(default=50, ge=0, le=100)
    assigned_node_id: str | None = None
    fallback_nodes: tuple[str, ...] = Field(default_factory=tuple)
    status: AssignmentStatus = AssignmentStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def _validate_required_capabilities(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value, sort=True)

    @field_validator("fallback_nodes", mode="before")
    @classmethod
    def _validate_fallback_nodes(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value, sort=False)

    @field_validator("deadline", "created_at", "updated_at", mode="before")
    @classmethod
    def _validate_task_datetime(cls, value: datetime | str | None) -> datetime | None:
        return _normalize_datetime(value) if value is not None else None


class ConflictResolution(BaseModel):
    """Concurrent modification conflict that needs a deterministic decision."""

    model_config = ConfigDict(frozen=True)

    conflict_id: str = Field(default_factory=_new_ulid, min_length=1)
    conflicting_nodes: tuple[str, ...] = Field(default_factory=tuple)
    resource_path: str = Field(..., min_length=1)
    resolution_strategy: ResolutionStrategy = ResolutionStrategy.MANUAL
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conflicting_nodes", mode="before")
    @classmethod
    def _validate_conflicting_nodes(cls, value: Iterable[object] | None) -> tuple[str, ...]:
        return _normalize_unique(value, sort=False)

    @field_validator("created_at", "resolved_at", mode="before")
    @classmethod
    def _validate_conflict_datetime(cls, value: datetime | str | None) -> datetime | None:
        return _normalize_datetime(value) if value is not None else None


class CoordinationProtocol:
    """Transport-independent distributed coordination kernel."""

    def __init__(
        self,
        registry: NodeRegistry,
        router: TaskRouter | None = None,
        *,
        heartbeat_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        if router is None:
            from reins.coordination.router import TaskRouter

            router = TaskRouter()
        self.registry = registry
        self.router = router
        self.heartbeat_timeout = heartbeat_timeout
        self._tasks: dict[str, TaskAssignment] = {}
        self._task_results: dict[str, dict[str, Any]] = {}
        self._task_errors: dict[str, dict[str, Any]] = {}
        self._conflicts: dict[str, ConflictResolution] = {}

    async def register_node(self, node: AgentNode) -> None:
        await self.registry.register_node(node)

    async def deregister_node(self, node_id: str) -> None:
        await self.registry.deregister_node(node_id)
        await self._rebalance_tasks()

    async def heartbeat(self, node_id: str) -> None:
        updated = await self.registry.heartbeat(node_id)
        if updated is None:
            raise ValueError(f"unknown node: {node_id}")

    async def assign_task(self, task: TaskAssignment) -> str:
        await self._detect_stale_nodes()
        candidates = await self.query_capabilities(list(task.required_capabilities))
        selected = await self._select_best_node(candidates, task)
        if selected is None:
            raise ValueError(f"no available node can satisfy task {task.task_id}")

        assigned = task.model_copy(
            update={
                "assigned_node_id": selected.node_id,
                "status": AssignmentStatus.ASSIGNED,
                "attempts": task.attempts + 1,
                "updated_at": _utc_now(),
            }
        )
        self._tasks[assigned.task_id] = assigned
        await self._increment_node_load(selected, assigned.task_id)
        return selected.node_id

    async def report_completion(self, task_id: str, result: dict[str, Any]) -> None:
        task = self._require_task(task_id)
        if task.assigned_node_id is None:
            raise ValueError(f"task is not assigned: {task_id}")

        self._task_results[task_id] = dict(result)
        completed = task.model_copy(
            update={"status": AssignmentStatus.COMPLETED, "updated_at": _utc_now()}
        )
        self._tasks[task_id] = completed
        await self.router.record_result(task.assigned_node_id, success=True)
        await self._decrement_node_load(task.assigned_node_id, task_id, success=True)

    async def report_failure(self, task_id: str, error: dict[str, Any]) -> None:
        task = self._require_task(task_id)
        if task.assigned_node_id is None:
            raise ValueError(f"task is not assigned: {task_id}")

        failed_node_id = task.assigned_node_id
        self._task_errors[task_id] = dict(error)
        await self.router.record_result(failed_node_id, success=False)
        await self._decrement_node_load(failed_node_id, task_id, success=False)

        fallback = await self._select_fallback_node(task, failed_node_id)
        if fallback is None:
            self._tasks[task_id] = task.model_copy(
                update={"status": AssignmentStatus.FAILED, "updated_at": _utc_now()}
            )
            return

        reassigned = task.model_copy(
            update={
                "assigned_node_id": fallback.node_id,
                "fallback_nodes": tuple(
                    node_id for node_id in task.fallback_nodes if node_id != fallback.node_id
                ),
                "status": AssignmentStatus.REASSIGNED,
                "attempts": task.attempts + 1,
                "updated_at": _utc_now(),
            }
        )
        self._tasks[task_id] = reassigned
        await self._increment_node_load(fallback, task_id)

    async def query_capabilities(self, required: list[str]) -> list[AgentNode]:
        required_set = set(required)
        nodes = await self.registry.list_nodes()
        return [
            node
            for node in nodes
            if node.is_routable and required_set.issubset(node.capabilities)
        ]

    async def resolve_conflict(self, conflict: ConflictResolution) -> dict[str, Any]:
        nodes = {
            node.node_id: node
            for node in await self.registry.list_nodes()
            if node.node_id in conflict.conflicting_nodes
        }
        strategy = ResolutionStrategy(conflict.resolution_strategy)
        resolved_by = conflict.resolved_by
        status = "resolved"

        if strategy is ResolutionStrategy.LAST_WRITER_WINS:
            if not nodes:
                raise ValueError("last_writer_wins requires at least one known conflicting node")
            resolved_by = max(nodes.values(), key=lambda node: node.last_heartbeat).node_id
        elif strategy is ResolutionStrategy.CONSENSUS:
            accepted = await self.request_consensus(
                {
                    "conflict_id": conflict.conflict_id,
                    "resource_path": conflict.resource_path,
                    "strategy": strategy.value,
                },
                list(conflict.conflicting_nodes),
            )
            resolved_by = "consensus" if accepted else None
            status = "resolved" if accepted else "unresolved"
        elif strategy is ResolutionStrategy.MERGE:
            resolved_by = resolved_by or "merge"
        elif strategy is ResolutionStrategy.MANUAL and not resolved_by:
            status = "manual_required"

        resolved = conflict.model_copy(
            update={
                "resolved_by": resolved_by,
                "resolved_at": _utc_now() if status == "resolved" else None,
            }
        )
        self._conflicts[resolved.conflict_id] = resolved
        return {
            "conflict_id": resolved.conflict_id,
            "resource_path": resolved.resource_path,
            "resolution_strategy": strategy.value,
            "resolved_by": resolved_by,
            "status": status,
        }

    async def request_consensus(self, proposal: dict[str, Any], voters: list[str]) -> bool:
        if not voters:
            return False
        nodes = {node.node_id: node for node in await self.registry.list_nodes()}
        eligible = [node_id for node_id in voters if node_id in nodes]
        positive_votes = [
            node_id
            for node_id in eligible
            if nodes[node_id].status in {NodeStatus.IDLE, NodeStatus.BUSY}
        ]
        required_votes = (len(eligible) // 2) + 1
        return len(positive_votes) >= required_votes

    async def get_task(self, task_id: str) -> TaskAssignment | None:
        return self._tasks.get(task_id)

    async def get_task_result(self, task_id: str) -> dict[str, Any] | None:
        return self._task_results.get(task_id)

    async def detect_stale_nodes(self) -> list[AgentNode]:
        return await self._detect_stale_nodes()

    async def rebalance_tasks(self) -> list[TaskAssignment]:
        return await self._rebalance_tasks()

    async def _select_best_node(
        self,
        candidates: list[AgentNode],
        task: TaskAssignment,
    ) -> AgentNode | None:
        return await self.router.route_task(candidates, task=task)

    async def _detect_stale_nodes(self) -> list[AgentNode]:
        cutoff = _utc_now() - self.heartbeat_timeout
        stale_nodes = [
            node
            for node in await self.registry.list_nodes()
            if node.status in {NodeStatus.IDLE, NodeStatus.BUSY}
            and node.last_heartbeat < cutoff
        ]
        for node in stale_nodes:
            await self.registry.update_status(node.node_id, NodeStatus.OFFLINE)
        return stale_nodes

    async def _rebalance_tasks(self) -> list[TaskAssignment]:
        moved: list[TaskAssignment] = []
        await self._detect_stale_nodes()
        nodes = {node.node_id: node for node in await self.registry.list_nodes()}
        unavailable = {
            node_id
            for node_id, node in nodes.items()
            if node.status in {NodeStatus.DRAINING, NodeStatus.OFFLINE}
        }

        for task in list(self._tasks.values()):
            if task.status not in {AssignmentStatus.ASSIGNED, AssignmentStatus.REASSIGNED}:
                continue
            if task.assigned_node_id not in unavailable:
                continue
            fallback = await self._select_fallback_node(task, task.assigned_node_id)
            if fallback is None:
                continue
            updated = task.model_copy(
                update={
                    "assigned_node_id": fallback.node_id,
                    "status": AssignmentStatus.REASSIGNED,
                    "attempts": task.attempts + 1,
                    "updated_at": _utc_now(),
                }
            )
            self._tasks[task.task_id] = updated
            await self._increment_node_load(fallback, task.task_id)
            moved.append(updated)
        return moved

    async def _select_fallback_node(
        self,
        task: TaskAssignment,
        failed_node_id: str | None,
    ) -> AgentNode | None:
        candidates = await self.query_capabilities(list(task.required_capabilities))
        excluded = {failed_node_id} if failed_node_id else set()
        candidates = [node for node in candidates if node.node_id not in excluded]
        if task.fallback_nodes:
            fallback_ids = set(task.fallback_nodes)
            preferred = [node for node in candidates if node.node_id in fallback_ids]
            candidates = preferred or candidates
        return await self._select_best_node(candidates, task)

    async def _increment_node_load(self, node: AgentNode, task_id: str) -> None:
        new_load = min(node.max_concurrent_tasks, node.current_load + 1)
        await self.registry.heartbeat(
            node.node_id,
            status=self._status_for_load(node, new_load),
            current_load=new_load,
            current_task_id=task_id,
        )

    async def _decrement_node_load(
        self,
        node_id: str,
        task_id: str,
        *,
        success: bool | None = None,
    ) -> None:
        node = await self.registry.get_node(node_id)
        if node is None:
            return
        new_load = max(0, node.current_load - 1)
        current_task_id = None if node.current_task_id == task_id else node.current_task_id
        updates: dict[str, Any] = {
            "status": self._status_for_load(node, new_load),
            "current_load": new_load,
            "current_task_id": current_task_id,
        }
        if success is True:
            updates["completed_tasks"] = node.completed_tasks + 1
        elif success is False:
            updates["failed_tasks"] = node.failed_tasks + 1
        await self.registry.heartbeat(node_id, **updates)

    def _status_for_load(self, node: AgentNode, current_load: int) -> NodeStatus:
        if node.status in {NodeStatus.DRAINING, NodeStatus.OFFLINE}:
            return node.status
        return NodeStatus.BUSY if current_load else NodeStatus.IDLE

    def _require_task(self, task_id: str) -> TaskAssignment:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        return task
