"""Persistent registry for active worktree-backed agents."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.worktree_events import (
    AGENT_HEARTBEAT_UPDATED,
    AGENT_REGISTERED,
    AGENT_UNREGISTERED,
)


@dataclass(frozen=True)
class AgentRegistryRecord:
    """Persistent state for a currently active agent."""

    agent_id: str
    worktree_id: str
    task_id: str | None
    status: str
    started_at: datetime
    last_heartbeat: datetime

    def to_dict(self) -> dict[str, str | None]:
        return {
            "agent_id": self.agent_id,
            "worktree_id": self.worktree_id,
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> AgentRegistryRecord:
        return cls(
            agent_id=str(data["agent_id"]),
            worktree_id=str(data["worktree_id"]),
            task_id=str(data["task_id"]) if data.get("task_id") is not None else None,
            status=str(data["status"]),
            started_at=datetime.fromisoformat(str(data["started_at"])),
            last_heartbeat=datetime.fromisoformat(str(data["last_heartbeat"])),
        )


class AgentRegistry:
    """Tracks active worktree-backed agents in a JSON file."""

    def __init__(
        self,
        path: Path,
        *,
        journal: EventJournal,
        run_id: str,
    ) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._journal = journal
        self._run_id = run_id
        self._builder = EventBuilder(journal)
        self._lock = asyncio.Lock()
        self._records = self._load_records()

    async def register(
        self,
        *,
        agent_id: str,
        worktree_id: str,
        task_id: str | None,
        status: str,
    ) -> AgentRegistryRecord:
        """Register an active agent and persist it."""
        async with self._lock:
            now = datetime.now(UTC)
            record = AgentRegistryRecord(
                agent_id=agent_id,
                worktree_id=worktree_id,
                task_id=task_id,
                status=status,
                started_at=now,
                last_heartbeat=now,
            )
            self._records[agent_id] = record
            await self._persist()

        await self._builder.commit(
            run_id=self._run_id,
            event_type=AGENT_REGISTERED,
            payload=record.to_dict(),
        )
        return record

    async def unregister(
        self,
        agent_id: str,
        *,
        final_status: str,
    ) -> AgentRegistryRecord | None:
        """Remove an active agent from the registry."""
        async with self._lock:
            record = self._records.pop(agent_id, None)
            if record is None:
                return None
            await self._persist()

        payload = record.to_dict()
        payload["final_status"] = final_status
        payload["unregistered_at"] = datetime.now(UTC).isoformat()
        await self._builder.commit(
            run_id=self._run_id,
            event_type=AGENT_UNREGISTERED,
            payload=payload,
        )
        return record

    async def heartbeat(
        self,
        agent_id: str,
        *,
        status: str | None = None,
    ) -> AgentRegistryRecord | None:
        """Update an agent heartbeat and optionally its status."""
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return None
            updated = AgentRegistryRecord(
                agent_id=record.agent_id,
                worktree_id=record.worktree_id,
                task_id=record.task_id,
                status=status or record.status,
                started_at=record.started_at,
                last_heartbeat=datetime.now(UTC),
            )
            self._records[agent_id] = updated
            await self._persist()

        await self._builder.commit(
            run_id=self._run_id,
            event_type=AGENT_HEARTBEAT_UPDATED,
            payload=updated.to_dict(),
        )
        return updated

    async def get(self, agent_id: str) -> AgentRegistryRecord | None:
        """Return a single agent record."""
        async with self._lock:
            return self._records.get(agent_id)

    async def list_all(self) -> list[AgentRegistryRecord]:
        """List all active agents."""
        async with self._lock:
            return sorted(self._records.values(), key=lambda record: record.agent_id)

    async def list_by_status(self, status: str) -> list[AgentRegistryRecord]:
        """List active agents filtered by status."""
        async with self._lock:
            return sorted(
                (
                    record
                    for record in self._records.values()
                    if record.status == status
                ),
                key=lambda record: record.agent_id,
            )

    async def list_by_task(self, task_id: str) -> list[AgentRegistryRecord]:
        """List active agents assigned to a task."""
        async with self._lock:
            return sorted(
                (
                    record
                    for record in self._records.values()
                    if record.task_id == task_id
                ),
                key=lambda record: record.agent_id,
            )

    def _load_records(self) -> dict[str, AgentRegistryRecord]:
        if not self._path.exists():
            return {}

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        agents = raw.get("agents", [])
        if not isinstance(agents, list):
            return {}
        return {
            record.agent_id: record
            for record in (
                AgentRegistryRecord.from_dict(item)
                for item in agents
                if isinstance(item, dict)
            )
        }

    async def _persist(self) -> None:
        payload = {
            "schema_version": 1,
            "agents": [record.to_dict() for record in self._records.values()],
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        await asyncio.to_thread(self._path.write_text, serialized, encoding="utf-8")
