from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

import ulid

from reins.kernel.types import ArtifactRef


@dataclass(frozen=True)
class Handle:
    """An open stateful environment handle."""

    adapter_kind: str
    adapter_id: str
    metadata: dict = field(default_factory=dict)
    handle_id: str = field(default_factory=lambda: str(ulid.new()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Observation:
    """Result of executing a command against an adapter handle."""

    stdout: str
    stderr: str
    exit_code: int
    artifacts: list[ArtifactRef] = field(default_factory=list)
    effect_descriptor: dict | None = None


class Adapter(ABC):
    @abstractmethod
    async def open(self, spec: dict) -> Handle: ...

    @abstractmethod
    async def exec(self, handle: Handle, command: dict) -> Observation: ...

    @abstractmethod
    async def snapshot(self, handle: Handle) -> str: ...

    @abstractmethod
    async def freeze(self, handle: Handle) -> dict: ...

    @abstractmethod
    async def thaw(self, frozen: dict) -> Handle: ...

    @abstractmethod
    async def reset(self, handle: Handle) -> Handle: ...

    @abstractmethod
    async def close(self, handle: Handle) -> None: ...
