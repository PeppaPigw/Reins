from __future__ import annotations

from typing import Any, Callable

EventPayload = dict[str, Any]
Upcaster = Callable[[EventPayload], EventPayload]


class UpcasterRegistry:
    def __init__(self) -> None:
        self._upcasters: dict[tuple[str, int], Upcaster] = {}
        self._current_versions: dict[str, int] = {}

    def register(self, event_type: str, from_version: int, upcaster: Upcaster) -> None:
        self._upcasters[(event_type, from_version)] = upcaster

    def set_current_version(self, event_type: str, version: int) -> None:
        self._current_versions[event_type] = version

    def get_current_version(self, event_type: str) -> int:
        return self._current_versions.get(event_type, 1)

    def upcast(self, event_type: str, payload: EventPayload, from_version: int) -> tuple[EventPayload, int]:
        target_version = self.get_current_version(event_type)
        current_payload = payload
        for v in range(from_version, target_version):
            upcaster = self._upcasters.get((event_type, v))
            if upcaster is not None:
                current_payload = upcaster(current_payload)
        return current_payload, target_version

    def needs_upcast(self, event_type: str, schema_version: int) -> bool:
        return schema_version < self.get_current_version(event_type)


_default_registry: UpcasterRegistry | None = None


def get_default_registry() -> UpcasterRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = UpcasterRegistry()
    return _default_registry


def register_upcaster(event_type: str, from_version: int, upcaster: Upcaster) -> None:
    get_default_registry().register(event_type, from_version, upcaster)
