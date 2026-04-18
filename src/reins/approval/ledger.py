"""Approval ledger with audit history and bounded delegation support."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import ulid

from reins.approval.audit import ApprovalAuditEntry, ApprovalAuditLog
from reins.approval.delegation import ApprovalDelegation, ApprovalDelegationLedger
from reins.serde import parse_dt, to_primitive, write_json_atomic


@dataclass(frozen=True)
class EffectDescriptor:
    """Concrete description of what an operation will do."""

    capability: str
    resource: str
    intent_ref: str
    command_id: str
    preview_ref: str | None = None
    rollback_strategy: str = (
        "none"  # none | reverse_patch | compensating_action | transaction
    )
    reversibility: str = (
        "irreversible"  # reversible | partially_reversible | irreversible
    )
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
class ApprovalStatusEntry:
    """Human-readable lifecycle entry for a request."""

    status: str
    actor: str
    recorded_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    run_id: str
    effect: EffectDescriptor
    requested_at: datetime
    requested_by: str  # skill, model, subagent
    reason: str | None = None
    required_approvers: tuple[str, ...] = ("human",)
    status: str = "pending"
    status_history: tuple[ApprovalStatusEntry, ...] = ()


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
    granted_by: str  # human, auto_policy, delegated actor
    delegated_by: str | None = None
    delegation_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ApprovalRejection:
    request_id: str
    run_id: str
    reason: str
    rejected_at: datetime
    rejected_by: str


class ApprovalLedger:
    """Persistent approval record with audit and delegation helpers."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._audit = ApprovalAuditLog(base_dir)
        self._delegations = ApprovalDelegationLedger(base_dir)
        self._pending = self._load_pending()

    async def request(
        self,
        run_id: str,
        effect: EffectDescriptor,
        requested_by: str,
        reason: str | None = None,
        required_approvers: list[str] | tuple[str, ...] | None = None,
    ) -> ApprovalRequest:
        requested_at = datetime.now(UTC)
        history = (
            ApprovalStatusEntry(
                status="pending",
                actor=requested_by,
                recorded_at=requested_at,
                note=reason,
            ),
        )
        req = ApprovalRequest(
            request_id=str(ulid.new()),
            run_id=run_id,
            effect=effect,
            requested_at=requested_at,
            requested_by=requested_by,
            reason=reason,
            required_approvers=tuple(required_approvers or ("human",)),
            status="pending",
            status_history=history,
        )
        self._pending[req.request_id] = req
        await self._persist_request(req)
        await self._audit.record(
            kind="request.created",
            actor=requested_by,
            request_id=req.request_id,
            run_id=run_id,
            capability=effect.capability,
            resource=effect.resource,
            details={
                "reason": reason,
                "required_approvers": list(req.required_approvers),
            },
            occurred_at=requested_at,
        )
        return req

    async def approve(
        self,
        request_id: str,
        granted_by: str = "human",
    ) -> ApprovalGrant | None:
        req = self._pending.get(request_id)
        if req is None:
            return None

        granted_at = datetime.now(UTC)
        delegation = self._resolve_delegation(req, granted_by, granted_at)
        self._pending.pop(request_id, None)

        grant = ApprovalGrant(
            grant_id=str(ulid.new()),
            request_id=request_id,
            run_id=req.run_id,
            descriptor_hash=req.effect.descriptor_hash,
            capability=req.effect.capability,
            scope=req.effect.resource,
            ttl_seconds=req.effect.ttl_seconds,
            granted_at=granted_at,
            granted_by=granted_by,
            delegated_by=delegation.from_actor if delegation else None,
            delegation_id=delegation.delegation_id if delegation else None,
            reason=req.reason,
        )
        updated = ApprovalRequest(
            request_id=req.request_id,
            run_id=req.run_id,
            effect=req.effect,
            requested_at=req.requested_at,
            requested_by=req.requested_by,
            reason=req.reason,
            required_approvers=req.required_approvers,
            status="approved",
            status_history=req.status_history
            + (
                ApprovalStatusEntry(
                    status="approved",
                    actor=granted_by,
                    recorded_at=granted_at,
                    note=req.reason,
                ),
            ),
        )
        await self._persist_request(updated)
        await self._persist("grants", grant.grant_id, to_primitive(grant))
        await self._audit.record(
            kind="request.approved",
            actor=granted_by,
            request_id=request_id,
            run_id=req.run_id,
            grant_id=grant.grant_id,
            delegation_id=grant.delegation_id,
            capability=req.effect.capability,
            resource=req.effect.resource,
            details={
                "delegated_by": grant.delegated_by,
                "required_approvers": list(req.required_approvers),
            },
            occurred_at=granted_at,
        )
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

        rejected_at = datetime.now(UTC)
        rej = ApprovalRejection(
            request_id=request_id,
            run_id=req.run_id,
            reason=reason,
            rejected_at=rejected_at,
            rejected_by=rejected_by,
        )
        updated = ApprovalRequest(
            request_id=req.request_id,
            run_id=req.run_id,
            effect=req.effect,
            requested_at=req.requested_at,
            requested_by=req.requested_by,
            reason=req.reason,
            required_approvers=req.required_approvers,
            status="rejected",
            status_history=req.status_history
            + (
                ApprovalStatusEntry(
                    status="rejected",
                    actor=rejected_by,
                    recorded_at=rejected_at,
                    note=reason,
                ),
            ),
        )
        await self._persist_request(updated)
        await self._persist("rejections", rej.request_id, to_primitive(rej))
        await self._audit.record(
            kind="request.rejected",
            actor=rejected_by,
            request_id=request_id,
            run_id=req.run_id,
            capability=req.effect.capability,
            resource=req.effect.resource,
            details={"reason": reason},
            occurred_at=rejected_at,
        )
        return rej

    async def delegate(
        self,
        *,
        from_actor: str,
        to_actor: str,
        scope: list[str] | tuple[str, ...],
        expires_at: datetime,
        resource_scope: list[str] | tuple[str, ...] | None = None,
        note: str | None = None,
    ) -> ApprovalDelegation:
        delegation = await self._delegations.delegate(
            from_actor=from_actor,
            to_actor=to_actor,
            scope=scope,
            expires_at=expires_at,
            resource_scope=resource_scope,
            note=note,
        )
        await self._audit.record(
            kind="delegation.created",
            actor=from_actor,
            delegation_id=delegation.delegation_id,
            capability=",".join(delegation.scope),
            resource=",".join(delegation.resource_scope),
            details={
                "to_actor": to_actor,
                "expires_at": delegation.expires_at.isoformat(),
                "note": note,
            },
            occurred_at=delegation.issued_at,
        )
        return delegation

    async def revoke_delegation(
        self,
        delegation_id: str,
        *,
        revoked_by: str,
    ) -> ApprovalDelegation | None:
        delegation = await self._delegations.revoke(
            delegation_id,
            revoked_by=revoked_by,
        )
        if delegation is None:
            return None
        await self._audit.record(
            kind="delegation.revoked",
            actor=revoked_by,
            delegation_id=delegation.delegation_id,
            capability=",".join(delegation.scope),
            resource=",".join(delegation.resource_scope),
            details={"to_actor": delegation.to_actor},
            occurred_at=delegation.revoked_at,
        )
        return delegation

    def audit(
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
        return self._audit.query(
            from_time=from_time,
            to_time=to_time,
            actor=actor,
            kind=kind,
            request_id=request_id,
            run_id=run_id,
            capability=capability,
            resource=resource,
        )

    @property
    def pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    async def _persist(self, kind: str, item_id: str, data: dict) -> None:
        path = self.base_dir / kind / f"{item_id}.json"
        await write_json_atomic(path, data)

    async def _persist_request(self, request: ApprovalRequest) -> None:
        await self._persist("requests", request.request_id, to_primitive(request))

    def _load_pending(self) -> dict[str, ApprovalRequest]:
        requests_dir = self.base_dir / "requests"
        if not requests_dir.exists():
            return {}

        resolved = self._resolved_request_ids()
        pending: dict[str, ApprovalRequest] = {}
        for path in sorted(requests_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            request = self._request_from_data(data)
            if request.request_id in resolved or request.status != "pending":
                continue
            pending[request.request_id] = request
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

    def _resolve_delegation(
        self,
        request: ApprovalRequest,
        granted_by: str,
        granted_at: datetime,
    ) -> ApprovalDelegation | None:
        if granted_by in request.required_approvers:
            return None
        delegation = self._delegations.find_active(
            actor=granted_by,
            capability=request.effect.capability,
            resource=request.effect.resource,
            required_from=request.required_approvers,
            at=granted_at,
        )
        if delegation is None:
            raise PermissionError(
                f"{granted_by} is not authorized to approve {request.effect.summary}"
            )
        return delegation

    @staticmethod
    def _request_from_data(data: dict) -> ApprovalRequest:
        status_history = tuple(
            ApprovalStatusEntry(
                status=item["status"],
                actor=item["actor"],
                recorded_at=parse_dt(item["recorded_at"]),
                note=item.get("note"),
            )
            for item in data.get("status_history", [])
        )
        requested_at = parse_dt(data["requested_at"])
        if not status_history:
            status_history = (
                ApprovalStatusEntry(
                    status=data.get("status", "pending"),
                    actor=data["requested_by"],
                    recorded_at=requested_at,
                    note=data.get("reason"),
                ),
            )
        return ApprovalRequest(
            request_id=data["request_id"],
            run_id=data["run_id"],
            effect=EffectDescriptor(**data["effect"]),
            requested_at=requested_at,
            requested_by=data["requested_by"],
            reason=data.get("reason"),
            required_approvers=tuple(data.get("required_approvers", ("human",))),
            status=data.get("status", "pending"),
            status_history=status_history,
        )
