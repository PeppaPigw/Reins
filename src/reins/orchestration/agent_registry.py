"""Agent registry for tracking active agents and their state.

Tracks all active agents in a persistent registry file (.reins/agents/registry.json).
Supports queries for monitoring, status updates, and cleanup.

Registry Schema:
{
  "agents": [
    {
      "agent_id": "agent-123",
      "agent_type": "implement",
      "task_id": "task-456",
      "worktree_path": "/path/to/worktree",
      "status": "running",
      "started_at": "2026-04-18T10:00:00Z",
      "pid": 12345
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import ulid

from reins.kernel.event.journal import EventJournal
from reins.kernel.event.builder import EventBuilder


@dataclass
class AgentMetadata:
    """Metadata for a registered agent."""

    agent_id: str
    agent_type: str
    task_id: str
    worktree_path: str | None
    status: str  # pending, running, completed, failed
    started_at: str
    completed_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    error_message: str | None = None


class AgentRegistry:
    """Registry for tracking active agents.

    Persistence: .reins/agents/registry.json

    Responsibilities:
    - Track active agents and their state
    - Persist registry to JSON file
    - Support queries for monitoring
    - Handle cleanup of completed agents
    - Emit registry events to EventJournal
    """

    def __init__(
        self,
        repo_root: Path,
        journal: EventJournal,
    ):
        """Initialize agent registry.

        Args:
            repo_root: Repository root directory
            journal: EventJournal for emitting events
        """
        self.repo_root = repo_root
        self.journal = journal
        self._event_builder = EventBuilder(journal)
        self._registry_dir = repo_root / ".reins" / "agents"
        self._registry_file = self._registry_dir / "registry.json"
        self._agents: dict[str, AgentMetadata] = {}

        # Ensure registry directory exists
        self._registry_dir.mkdir(parents=True, exist_ok=True)

        # Load existing registry
        self._load_registry()

    def _load_registry(self) -> None:
        """Load registry from JSON file."""
        if not self._registry_file.exists():
            return

        try:
            data = json.loads(self._registry_file.read_text())
            for agent_dict in data.get("agents", []):
                agent = AgentMetadata(**agent_dict)
                self._agents[agent.agent_id] = agent
        except (json.JSONDecodeError, TypeError) as e:
            # Corrupted registry, start fresh
            print(f"Warning: Failed to load agent registry: {e}")
            self._agents = {}

    def _save_registry(self) -> None:
        """Save registry to JSON file."""
        data = {
            "agents": [asdict(agent) for agent in self._agents.values()],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._registry_file.write_text(json.dumps(data, indent=2))

    async def register_agent(
        self,
        agent_type: str,
        task_id: str,
        run_id: str,
        worktree_path: str | None = None,
        pid: int | None = None,
        agent_id: str | None = None,
    ) -> str:
        """Register a new agent.

        Args:
            agent_type: Agent type (implement, check, debug, research)
            task_id: Task ID the agent is working on
            run_id: Run ID for event emission
            worktree_path: Optional worktree path
            pid: Optional process ID
            agent_id: Optional precomputed agent ID to persist

        Returns:
            Persisted agent ID
        """
        agent_id = agent_id or f"agent-{ulid.new()}"

        agent = AgentMetadata(
            agent_id=agent_id,
            agent_type=agent_type,
            task_id=task_id,
            worktree_path=worktree_path,
            status="pending",
            started_at=datetime.now(UTC).isoformat(),
            pid=pid,
        )

        self._agents[agent_id] = agent
        self._save_registry()

        # Emit event
        await self._event_builder.commit(
            run_id=run_id,
            event_type="agent.registered",
            payload={
                "agent_id": agent_id,
                "agent_type": agent_type,
                "task_id": task_id,
                "worktree_path": worktree_path,
            },
        )

        return agent_id

    async def update_status(
        self,
        agent_id: str,
        status: str,
        run_id: str,
        exit_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update agent status.

        Args:
            agent_id: Agent ID to update
            status: New status (pending, running, completed, failed)
            run_id: Run ID for event emission
            exit_code: Optional exit code (for completed/failed)
            error_message: Optional error message (for failed)
        """
        if agent_id not in self._agents:
            raise ValueError(f"Agent {agent_id} not found in registry")

        agent = self._agents[agent_id]
        old_status = agent.status
        agent.status = status

        if status in ("completed", "failed"):
            agent.completed_at = datetime.now(UTC).isoformat()
            agent.exit_code = exit_code
            agent.error_message = error_message

        self._save_registry()

        # Emit event
        await self._event_builder.commit(
            run_id=run_id,
            event_type="agent.status_changed",
            payload={
                "agent_id": agent_id,
                "old_status": old_status,
                "new_status": status,
                "exit_code": exit_code,
                "error_message": error_message,
            },
        )

    def get_agent(self, agent_id: str) -> AgentMetadata | None:
        """Get agent metadata by ID.

        Args:
            agent_id: Agent ID to retrieve

        Returns:
            AgentMetadata or None if not found
        """
        return self._agents.get(agent_id)

    def get_active_agents(self) -> list[AgentMetadata]:
        """Get all active agents (pending or running).

        Returns:
            List of active AgentMetadata
        """
        return [
            agent
            for agent in self._agents.values()
            if agent.status in ("pending", "running")
        ]

    def get_agents_by_task(self, task_id: str) -> list[AgentMetadata]:
        """Get all agents for a specific task.

        Args:
            task_id: Task ID to filter by

        Returns:
            List of AgentMetadata for the task
        """
        return [
            agent for agent in self._agents.values() if agent.task_id == task_id
        ]

    def get_agents_by_type(self, agent_type: str) -> list[AgentMetadata]:
        """Get all agents of a specific type.

        Args:
            agent_type: Agent type to filter by

        Returns:
            List of AgentMetadata of the type
        """
        return [
            agent for agent in self._agents.values() if agent.agent_type == agent_type
        ]

    async def cleanup_agent(
        self,
        agent_id: str,
        run_id: str,
    ) -> None:
        """Remove agent from registry (cleanup after completion).

        Args:
            agent_id: Agent ID to remove
            run_id: Run ID for event emission
        """
        if agent_id not in self._agents:
            return

        agent = self._agents[agent_id]
        del self._agents[agent_id]
        self._save_registry()

        # Emit event
        await self._event_builder.commit(
            run_id=run_id,
            event_type="agent.cleanup_completed",
            payload={
                "agent_id": agent_id,
                "agent_type": agent.agent_type,
                "task_id": agent.task_id,
                "final_status": agent.status,
            },
        )

    def get_registry_stats(self) -> dict[str, Any]:
        """Get registry statistics.

        Returns:
            Dict with registry stats
        """
        total = len(self._agents)
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for agent in self._agents.values():
            by_status[agent.status] = by_status.get(agent.status, 0) + 1
            by_type[agent.agent_type] = by_type.get(agent.agent_type, 0) + 1

        return {
            "total_agents": total,
            "by_status": by_status,
            "by_type": by_type,
            "active_count": len(self.get_active_agents()),
        }
