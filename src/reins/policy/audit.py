"""Structured audit records for policy decisions.

The policy engine can emit audit records without changing orchestration events.
That keeps the default runtime behavior intact while making higher-level policy
evaluation observable for tests, analysis, or filesystem-backed audit trails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import aiofiles  # type: ignore[import-untyped]

from reins.serde import canonical_json


@dataclass(frozen=True)
class PolicyAuditRecord:
    """Serializable record of a single policy decision."""

    recorded_at: datetime
    run_id: str
    capability: str
    requested_by: str
    risk_tier: int
    decision: str
    reason: str
    resource: str | None = None
    descriptor_hash: str | None = None
    grant_id: str | None = None
    base_decision: str | None = None
    matched_rule: str | None = None
    triggered_constraints: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        capability: str,
        requested_by: str,
        risk_tier: int,
        decision: str,
        reason: str,
        resource: str | None = None,
        descriptor_hash: str | None = None,
        grant_id: str | None = None,
        base_decision: str | None = None,
        matched_rule: str | None = None,
        triggered_constraints: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> "PolicyAuditRecord":
        return cls(
            recorded_at=datetime.now(UTC),
            run_id=run_id,
            capability=capability,
            requested_by=requested_by,
            risk_tier=risk_tier,
            decision=decision,
            reason=reason,
            resource=resource,
            descriptor_hash=descriptor_hash,
            grant_id=grant_id,
            base_decision=base_decision,
            matched_rule=matched_rule,
            triggered_constraints=triggered_constraints,
            metadata=metadata or {},
        )


class PolicyAuditSink(Protocol):
    """Minimal sink interface used by the policy engine."""

    async def record(self, record: PolicyAuditRecord) -> None:
        """Persist or capture a policy audit record."""


class InMemoryPolicyAuditSink:
    """Lightweight sink for tests and in-process introspection."""

    def __init__(self) -> None:
        self.records: list[PolicyAuditRecord] = []

    async def record(self, record: PolicyAuditRecord) -> None:
        self.records.append(record)


class JsonlPolicyAuditSink:
    """Append-only JSONL sink for offline auditing."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def record(self, record: PolicyAuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.path, "a", encoding="utf-8") as handle:
            await handle.write(canonical_json(record))
            await handle.write("\n")
