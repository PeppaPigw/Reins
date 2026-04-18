"""TTL cache for compiled context payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reins.context.compiler import CompiledContext


@dataclass
class ContextCacheEntry:
    key: str
    value: "CompiledContext"
    stored_at: datetime
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


class ContextCache:
    """In-memory cache with TTL semantics for compiled context."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, ContextCacheEntry] = {}

    def get(self, key: str) -> "CompiledContext" | None:
        self.prune()
        entry = self._entries.get(key)
        if entry is None or entry.expired:
            self._entries.pop(key, None)
            return None
        return entry.value

    def set(
        self,
        key: str,
        value: "CompiledContext",
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        stored_at = datetime.now(UTC)
        self._entries[key] = ContextCacheEntry(
            key=key,
            value=value,
            stored_at=stored_at,
            expires_at=stored_at + timedelta(seconds=ttl),
        )

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
            return
        self._entries.pop(key, None)

    def prune(self) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expired]
        for key in expired:
            self._entries.pop(key, None)

    def __len__(self) -> int:
        self.prune()
        return len(self._entries)
