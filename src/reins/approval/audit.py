"""Audit records and query helpers for approval activity."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.serde import parse_dt, to_primitive, write_json_atomic


@dataclass(frozen=True)
class ApprovalAuditEntry:
    """Single auditable approval-domain action."""

    entry_id: str
    kind: str
    actor: str
    occurred_at: datetime
    request_id: str | None = None
    run_id: str | None = None
    grant_id: str | None = None
    delegation_id: str | None = None
    capability: str | None = None
    resource: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ApprovalAuditLog:
    """Persist and query approval audit entries."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    async def record(
        self,
        *,
        kind: str,
        actor: str,
        request_id: str | None = None,
        run_id: str | None = None,
        grant_id: str | None = None,
        delegation_id: str | None = None,
        capability: str | None = None,
        resource: str | None = None,
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> ApprovalAuditEntry:
        entry = ApprovalAuditEntry(
            entry_id=str(ulid.new()),
            kind=kind,
            actor=actor,
            occurred_at=occurred_at or datetime.now(UTC),
            request_id=request_id,
            run_id=run_id,
            grant_id=grant_id,
            delegation_id=delegation_id,
            capability=capability,
            resource=resource,
            details=details or {},
        )
        await self._persist(entry)
        return entry

    def query(
        self,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        actor: str | None = None,
        kind: str | None = None,
        request_id: str | None = None,
        run_id: str | None = None,
        capability: str | None = None,
        resource: str | None = None,
    ) -> list[ApprovalAuditEntry]:
        entries = self._load_all()
        return [
            entry
            for entry in entries
            if self._matches(
                entry,
                from_time=from_time,
                to_time=to_time,
                actor=actor,
                kind=kind,
                request_id=request_id,
                run_id=run_id,
                capability=capability,
                resource=resource,
            )
        ]

    async def _persist(self, entry: ApprovalAuditEntry) -> None:
        path = self._base_dir / "audit" / f"{entry.entry_id}.json"
        await write_json_atomic(path, to_primitive(entry))

    def _load_all(self) -> list[ApprovalAuditEntry]:
        audit_dir = self._base_dir / "audit"
        if not audit_dir.exists():
            return []
        entries: list[ApprovalAuditEntry] = []
        for path in sorted(audit_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            entries.append(
                ApprovalAuditEntry(
                    entry_id=data["entry_id"],
                    kind=data["kind"],
                    actor=data["actor"],
                    occurred_at=parse_dt(data["occurred_at"]),
                    request_id=data.get("request_id"),
                    run_id=data.get("run_id"),
                    grant_id=data.get("grant_id"),
                    delegation_id=data.get("delegation_id"),
                    capability=data.get("capability"),
                    resource=data.get("resource"),
                    details=data.get("details", {}),
                )
            )
        return entries

    @staticmethod
    def _matches(
        entry: ApprovalAuditEntry,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        actor: str | None,
        kind: str | None,
        request_id: str | None,
        run_id: str | None,
        capability: str | None,
        resource: str | None,
    ) -> bool:
        if from_time is not None and entry.occurred_at < from_time:
            return False
        if to_time is not None and entry.occurred_at > to_time:
            return False
        if actor is not None and entry.actor != actor:
            return False
        if kind is not None and entry.kind != kind:
            return False
        if request_id is not None and entry.request_id != request_id:
            return False
        if run_id is not None and entry.run_id != run_id:
            return False
        if capability is not None and entry.capability != capability:
            return False
        if resource is not None and entry.resource != resource:
            return False
        return True
