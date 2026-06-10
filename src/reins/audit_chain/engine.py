from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from reins.audit_chain.types import (
    AuditAction,
    AuditChainStats,
    AuditEntry,
    AuditQuery,
    AuditSeverity,
    ChainVerification,
    IntegrityStatus,
)


class AuditChain:
    """Tamper-evident audit chain with cryptographic linking.

    Each entry is hash-linked to its predecessor, forming an append-only
    chain that detects tampering. Provides SOC2/HIPAA-grade audit logging
    for agent actions with query, verification, and export capabilities.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._last_hash: str = "genesis"

    def record(self, action: AuditAction, agent_id: str = "",
               subject: str = "", details: dict[str, Any] | None = None,
               severity: AuditSeverity = AuditSeverity.INFO) -> AuditEntry:
        sequence = len(self._entries)
        previous_hash = self._last_hash

        entry_data = {
            "sequence": sequence,
            "action": action.value,
            "agent_id": agent_id,
            "subject": subject,
            "details": details or {},
            "previous_hash": previous_hash,
        }
        entry_hash = self._compute_hash(entry_data)

        entry = AuditEntry(
            sequence=sequence,
            action=action,
            severity=severity,
            agent_id=agent_id,
            subject=subject,
            details=details or {},
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )
        self._entries.append(entry)
        self._last_hash = entry_hash
        return entry

    def query(self, q: AuditQuery | None = None) -> list[AuditEntry]:
        entries = self._entries
        if not q:
            return list(entries)

        if q.agent_id:
            entries = [e for e in entries if e.agent_id == q.agent_id]
        if q.action:
            entries = [e for e in entries if e.action == q.action]
        if q.severity:
            entries = [e for e in entries if e.severity == q.severity]
        if q.from_sequence is not None:
            entries = [e for e in entries if e.sequence >= q.from_sequence]
        if q.to_sequence is not None:
            entries = [e for e in entries if e.sequence <= q.to_sequence]

        return entries[:q.limit]

    def verify(self) -> ChainVerification:
        if not self._entries:
            return ChainVerification(
                status=IntegrityStatus.VALID,
                entries_checked=0,
                message="Empty chain",
            )

        prev_hash = "genesis"
        for i, entry in enumerate(self._entries):
            if entry.previous_hash != prev_hash:
                return ChainVerification(
                    status=IntegrityStatus.BROKEN_CHAIN,
                    entries_checked=i,
                    first_invalid=i,
                    message=f"Chain break at entry {i}: "
                            f"expected prev={prev_hash}, got={entry.previous_hash}",
                )

            expected_data = {
                "sequence": entry.sequence,
                "action": entry.action.value,
                "agent_id": entry.agent_id,
                "subject": entry.subject,
                "details": entry.details,
                "previous_hash": entry.previous_hash,
            }
            expected_hash = self._compute_hash(expected_data)
            if entry.entry_hash != expected_hash:
                return ChainVerification(
                    status=IntegrityStatus.TAMPERED,
                    entries_checked=i,
                    first_invalid=i,
                    message=f"Tampered entry at {i}: hash mismatch",
                )
            prev_hash = entry.entry_hash

        return ChainVerification(
            status=IntegrityStatus.VALID,
            entries_checked=len(self._entries),
            message=f"All {len(self._entries)} entries verified",
        )

    def get_entry(self, sequence: int) -> AuditEntry | None:
        if 0 <= sequence < len(self._entries):
            return self._entries[sequence]
        return None

    def get_latest(self, n: int = 10) -> list[AuditEntry]:
        return self._entries[-n:]

    def export_range(self, from_seq: int, to_seq: int) -> list[dict[str, Any]]:
        entries = [e for e in self._entries if from_seq <= e.sequence <= to_seq]
        return [e.model_dump() for e in entries]

    def get_stats(self) -> AuditChainStats:
        by_action: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        by_agent: dict[str, int] = defaultdict(int)

        for e in self._entries:
            by_action[e.action.value] += 1
            by_severity[e.severity.value] += 1
            if e.agent_id:
                by_agent[e.agent_id] += 1

        verification = self.verify()

        return AuditChainStats(
            total_entries=len(self._entries),
            integrity_status=verification.status,
            by_action=dict(by_action),
            by_severity=dict(by_severity),
            by_agent=dict(by_agent),
        )

    def _compute_hash(self, data: dict[str, Any]) -> str:
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()
