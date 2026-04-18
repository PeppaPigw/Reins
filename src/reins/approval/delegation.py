"""Delegation records for bounded approval authority."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import ulid

from reins.serde import parse_dt, to_primitive, write_json_atomic


@dataclass(frozen=True)
class ApprovalDelegation:
    """Delegates approval authority from one actor to another."""

    delegation_id: str
    from_actor: str
    to_actor: str
    scope: tuple[str, ...]
    resource_scope: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    note: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def is_active(self, at: datetime | None = None) -> bool:
        check_time = at or datetime.now(UTC)
        if self.revoked_at is not None and self.revoked_at <= check_time:
            return False
        return self.issued_at <= check_time <= self.expires_at

    def allows(
        self,
        *,
        capability: str,
        resource: str,
        at: datetime | None = None,
    ) -> bool:
        if not self.is_active(at):
            return False
        capability_allowed = any(
            fnmatch.fnmatch(capability, pattern) for pattern in self.scope
        )
        if not capability_allowed:
            return False
        return any(fnmatch.fnmatch(resource, pattern) for pattern in self.resource_scope)


class ApprovalDelegationLedger:
    """Persistent delegation store with scope and expiry checks."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    async def delegate(
        self,
        *,
        from_actor: str,
        to_actor: str,
        scope: list[str] | tuple[str, ...],
        expires_at: datetime,
        resource_scope: list[str] | tuple[str, ...] | None = None,
        note: str | None = None,
        issued_at: datetime | None = None,
    ) -> ApprovalDelegation:
        issued = issued_at or datetime.now(UTC)
        if expires_at <= issued:
            raise ValueError("delegation expiry must be after issue time")
        delegation = ApprovalDelegation(
            delegation_id=str(ulid.new()),
            from_actor=from_actor,
            to_actor=to_actor,
            scope=tuple(scope),
            resource_scope=tuple(resource_scope or ("*",)),
            issued_at=issued,
            expires_at=expires_at,
            note=note,
        )
        await self._persist(delegation)
        return delegation

    async def revoke(
        self,
        delegation_id: str,
        *,
        revoked_by: str,
        revoked_at: datetime | None = None,
    ) -> ApprovalDelegation | None:
        delegation = self.get(delegation_id)
        if delegation is None:
            return None
        updated = ApprovalDelegation(
            delegation_id=delegation.delegation_id,
            from_actor=delegation.from_actor,
            to_actor=delegation.to_actor,
            scope=delegation.scope,
            resource_scope=delegation.resource_scope,
            issued_at=delegation.issued_at,
            expires_at=delegation.expires_at,
            note=delegation.note,
            revoked_at=revoked_at or datetime.now(UTC),
            revoked_by=revoked_by,
        )
        await self._persist(updated)
        return updated

    def get(self, delegation_id: str) -> ApprovalDelegation | None:
        path = self._base_dir / "delegations" / f"{delegation_id}.json"
        if not path.exists():
            return None
        return self._from_data(json.loads(path.read_text(encoding="utf-8")))

    def active_for(
        self,
        actor: str,
        *,
        at: datetime | None = None,
    ) -> list[ApprovalDelegation]:
        return [
            delegation
            for delegation in self._load_all()
            if delegation.to_actor == actor and delegation.is_active(at)
        ]

    def find_active(
        self,
        *,
        actor: str,
        capability: str,
        resource: str,
        required_from: tuple[str, ...] | None = None,
        at: datetime | None = None,
    ) -> ApprovalDelegation | None:
        candidates = []
        for delegation in self.active_for(actor, at=at):
            if required_from is not None and delegation.from_actor not in required_from:
                continue
            if delegation.allows(capability=capability, resource=resource, at=at):
                candidates.append(delegation)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.issued_at, reverse=True)
        return candidates[0]

    async def _persist(self, delegation: ApprovalDelegation) -> None:
        path = self._base_dir / "delegations" / f"{delegation.delegation_id}.json"
        await write_json_atomic(path, to_primitive(delegation))

    def _load_all(self) -> list[ApprovalDelegation]:
        directory = self._base_dir / "delegations"
        if not directory.exists():
            return []
        return [
            self._from_data(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]

    @staticmethod
    def _from_data(data: dict) -> ApprovalDelegation:
        return ApprovalDelegation(
            delegation_id=data["delegation_id"],
            from_actor=data["from_actor"],
            to_actor=data["to_actor"],
            scope=tuple(data.get("scope", ())),
            resource_scope=tuple(data.get("resource_scope", ("*",))),
            issued_at=parse_dt(data["issued_at"]),
            expires_at=parse_dt(data["expires_at"]),
            note=data.get("note"),
            revoked_at=parse_dt(data["revoked_at"]) if data.get("revoked_at") else None,
            revoked_by=data.get("revoked_by"),
        )
