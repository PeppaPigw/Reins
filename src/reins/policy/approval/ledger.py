"""Approval ledger — persistent record of approval requests, grants, and rejections.

Every approval binds to a concrete EffectDescriptor hash, not just a text prompt.
Grants are TTL-bound, scoped, and revocable.  The ledger is the audit trail.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import ulid

from reins.serde import parse_dt, to_primitive, write_json_atomic


@dataclass(frozen=True)
class EffectDescriptor:
    """Concrete description of what an operation will do."""

    capability: str
    resource: str
    intent_ref: str
    command_id: str
    preview_ref: str | None = None
    rollback_strategy: str = "none"  # none | reverse_patch | compensating_action | transaction
    reversibility: str = "irreversible"  # reversible | partially_reversible | irreversible
    side_effects: list[str] = field(default_factory=list)
    ttl_seconds: int = 600

    @property
    def descriptor_hash(self) -> str:
        stable_fields = {
            "capability": self.capability,
            "resource": self.resource,
            "preview_ref": self.preview_ref,
            "rollback_strategy": self.rollback_strategy,
            "reversibility": self.reversibility,
            "side_effects": self.side_effects,
            "ttl_seconds": self.ttl_seconds,
        }
        blob = json.dumps(stable_fields, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]

    @property
    def summary(self) -> str:
        return f"{self.capability} -> {self.resource}"


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    run_id: str
    effect: EffectDescriptor
    requested_at: datetime
    requested_by: str  # skill, model, subagent


@dataclass(frozen=True)
class ApprovalGrant:
    grant_id: str
    request_id: str
    run_id: str
    descriptor_hash: str
    capability: str
    scope: str
    ttl_seconds: int
    granted_at: datetime
    granted_by: str  # human, auto_policy


@dataclass(frozen=True)
class ApprovalRejection:
    request_id: str
    run_id: str
    reason: str
    rejected_at: datetime
    rejected_by: str


class ApprovalLedger:
    """Persistent append-only approval record."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._pending = self._load_pending()

    async def request(
        self,
        run_id: str,
        effect: EffectDescriptor,
        requested_by: str,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            request_id=str(ulid.new()),
            run_id=run_id,
            effect=effect,
            requested_at=datetime.now(UTC),
            requested_by=requested_by,
        )
        self._pending[req.request_id] = req
        await self._persist("requests", req.request_id, to_primitive(req))
        return req

    async def approve(
        self,
        request_id: str,
        granted_by: str = "human",
    ) -> ApprovalGrant | None:
        req = self._pending.pop(request_id, None)
        if req is None:
            return None
        grant = ApprovalGrant(
            grant_id=str(ulid.new()),
            request_id=request_id,
            run_id=req.run_id,
            descriptor_hash=req.effect.descriptor_hash,
            capability=req.effect.capability,
            scope=req.effect.resource,
            ttl_seconds=req.effect.ttl_seconds,
            granted_at=datetime.now(UTC),
            granted_by=granted_by,
        )
        await self._persist("grants", grant.grant_id, to_primitive(grant))
        return grant

    async def reject(
        self,
        request_id: str,
        reason: str,
        rejected_by: str = "human",
    ) -> ApprovalRejection | None:
        req = self._pending.pop(request_id, None)
        if req is None:
            return None
        rej = ApprovalRejection(
            request_id=request_id,
            run_id=req.run_id,
            reason=reason,
            rejected_at=datetime.now(UTC),
            rejected_by=rejected_by,
        )
        await self._persist("rejections", rej.request_id, to_primitive(rej))
        return rej

    @property
    def pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    async def _persist(self, kind: str, item_id: str, data: dict) -> None:
        path = self.base_dir / kind / f"{item_id}.json"
        await write_json_atomic(path, data)

    def _load_pending(self) -> dict[str, ApprovalRequest]:
        requests_dir = self.base_dir / "requests"
        if not requests_dir.exists():
            return {}

        resolved = self._resolved_request_ids()
        pending: dict[str, ApprovalRequest] = {}
        for path in sorted(requests_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            request_id = data["request_id"]
            if request_id in resolved:
                continue
            pending[request_id] = ApprovalRequest(
                request_id=request_id,
                run_id=data["run_id"],
                effect=EffectDescriptor(**data["effect"]),
                requested_at=parse_dt(data["requested_at"]),
                requested_by=data["requested_by"],
            )
        return pending

    def _resolved_request_ids(self) -> set[str]:
        resolved: set[str] = set()
        for kind in ("grants", "rejections"):
            directory = self.base_dir / kind
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                data = json.loads(path.read_text(encoding="utf-8"))
                resolved.add(data["request_id"])
        return resolved
