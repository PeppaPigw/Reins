from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentExecutionRequest:
    """Request to execute an agent via a concrete backend."""

    agent_type: str
    prompt: str
    context: dict[str, Any]
    task_dir: Path
    model: str | None = None


@dataclass
class AgentExecutionResult:
    """Result returned by an agent execution backend."""

    success: bool
    output: str
    artifacts: list[Path]
    error: str | None = None
    exit_code: int | None = None


class AgentExecutionAdapter(ABC):
    """Adapter for executing agents via different backends."""

    @abstractmethod
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Execute an agent and return the result."""

    @abstractmethod
    def supports_agent_type(self, agent_type: str) -> bool:
        """Check whether this adapter supports the given agent type."""
