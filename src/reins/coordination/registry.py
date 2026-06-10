from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]
import ulid
from pydantic import BaseModel, ConfigDict, Field, field_validator

from reins.coordination.protocol import AgentNode, NodeStatus, _normalize_datetime

NODE_REGISTERED = "node.registered"
NODE_DEREGISTERED = "node.deregistered"
NODE_HEARTBEAT = "node.heartbeat"
NODE_STATUS_CHANGED = "node.status_changed"

NODE_EVENT_TYPES = frozenset(
    {
        NODE_REGISTERED,
        NODE_DEREGISTERED,
        NODE_HEARTBEAT,
        NODE_STATUS_CHANGED,
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _replace_node(node: AgentNode, **updates: Any) -> AgentNode:
    data = node.model_dump()
    data.update(updates)
    return AgentNode.model_validate(data)


class NodeRegistryEvent(BaseModel):
    """Append-only registry event persisted as JSONL."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(ulid.new()), min_length=1)
    type: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)
    schema_version: int = 1

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in NODE_EVENT_TYPES:
            raise ValueError(f"unknown node registry event type: {value}")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: datetime | str) -> datetime:
        return _normalize_datetime(value)


class NodeRegistry:
    """Event-sourced registry of known distributed agent nodes."""

    def __init__(self, journal_path: Path | str) -> None:
        self.path = Path(journal_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = asyncio.Lock()
        self._nodes: dict[str, AgentNode] = {}
        self._replay_sync()

    async def register_node(self, node: AgentNode) -> None:
        event = NodeRegistryEvent(
            type=NODE_REGISTERED,
            node_id=node.node_id,
            payload={"node": node.model_dump(mode="json")},
        )
        async with self._lock:
            await self._append_event(event)
            self._apply_event(event)

    async def deregister_node(self, node_id: str) -> None:
        async with self._lock:
            event = NodeRegistryEvent(
                type=NODE_DEREGISTERED,
                node_id=node_id,
                payload={"deregistered_at": _utc_now().isoformat()},
            )
            await self._append_event(event)
            self._apply_event(event)

    async def heartbeat(
        self,
        node_id: str,
        *,
        status: NodeStatus | str | None = None,
        current_load: int | None = None,
        current_task_id: str | None = None,
        completed_tasks: int | None = None,
        failed_tasks: int | None = None,
        trust_score: float | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat_at: datetime | None = None,
    ) -> AgentNode | None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            updates: dict[str, Any] = {"last_heartbeat": heartbeat_at or _utc_now()}
            if status is not None:
                updates["status"] = NodeStatus(status)
            if current_load is not None:
                updates["current_load"] = current_load
            if current_task_id is not None or current_load == 0:
                updates["current_task_id"] = current_task_id
            if completed_tasks is not None:
                updates["completed_tasks"] = completed_tasks
            if failed_tasks is not None:
                updates["failed_tasks"] = failed_tasks
            if trust_score is not None:
                updates["trust_score"] = trust_score
            if metadata is not None:
                updates["metadata"] = dict(metadata)

            updated = _replace_node(node, **updates)
            event = NodeRegistryEvent(
                type=NODE_HEARTBEAT,
                node_id=node_id,
                payload={"node": updated.model_dump(mode="json")},
            )
            await self._append_event(event)
            self._apply_event(event)
            return updated

    async def update_status(self, node_id: str, status: NodeStatus | str) -> AgentNode | None:
        async with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            updated = _replace_node(
                node,
                status=NodeStatus(status),
                current_load=0 if NodeStatus(status) is NodeStatus.OFFLINE else node.current_load,
                current_task_id=None
                if NodeStatus(status) is NodeStatus.OFFLINE
                else node.current_task_id,
                last_heartbeat=_utc_now(),
            )
            event = NodeRegistryEvent(
                type=NODE_STATUS_CHANGED,
                node_id=node_id,
                payload={
                    "node": updated.model_dump(mode="json"),
                    "old_status": node.status.value,
                    "new_status": updated.status.value,
                },
            )
            await self._append_event(event)
            self._apply_event(event)
            return updated

    async def replay(self) -> list[NodeRegistryEvent]:
        async with self._lock:
            self._nodes = {}
            events: list[NodeRegistryEvent] = []
            async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
                async for line in handle:
                    if not line.strip():
                        continue
                    event = NodeRegistryEvent.model_validate_json(line)
                    self._apply_event(event)
                    events.append(event)
            return events

    async def get_node(self, node_id: str) -> AgentNode | None:
        async with self._lock:
            return self._nodes.get(node_id)

    async def list_nodes(self) -> list[AgentNode]:
        async with self._lock:
            return sorted(self._nodes.values(), key=lambda node: node.node_id)

    async def get_idle_nodes(self) -> list[AgentNode]:
        return [
            node
            for node in await self.list_nodes()
            if node.status is NodeStatus.IDLE and node.current_load < node.max_concurrent_tasks
        ]

    async def get_nodes_with_capability(self, capability: str) -> list[AgentNode]:
        return [
            node
            for node in await self.list_nodes()
            if capability in node.capabilities and node.status is not NodeStatus.OFFLINE
        ]

    async def get_node_load(self, node_id: str | None = None) -> int | dict[str, int]:
        nodes = await self.list_nodes()
        if node_id is None:
            return {node.node_id: node.current_load for node in nodes}
        node = next((item for item in nodes if item.node_id == node_id), None)
        if node is None:
            raise ValueError(f"unknown node: {node_id}")
        return node.current_load

    def _replay_sync(self) -> None:
        self._nodes = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = NodeRegistryEvent.model_validate_json(line)
            self._apply_event(event)

    async def _append_event(self, event: NodeRegistryEvent) -> None:
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
        async with aiofiles.open(self.path, "a", encoding="utf-8") as handle:
            await handle.write(line)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())

    def _apply_event(self, event: NodeRegistryEvent) -> None:
        if event.type == NODE_DEREGISTERED:
            self._nodes.pop(event.node_id, None)
            return
        node_payload = event.payload.get("node")
        if isinstance(node_payload, dict):
            self._nodes[event.node_id] = AgentNode.model_validate(node_payload)
