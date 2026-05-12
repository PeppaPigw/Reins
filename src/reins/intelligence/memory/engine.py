from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ulid

from reins.intelligence.types import MemoryQuery, MemoryRecord, MemoryType, ScoredMemory


class MemoryEngine:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._store_path / "memory_journal.jsonl"
        self._records: dict[str, MemoryRecord] = {}
        self._access_counts: dict[str, int] = {}
        self._created_at: dict[str, str] = {}
        self._load_journal()

    def _load_journal(self) -> None:
        if not self._journal_path.exists():
            return
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            self._apply_event(event)

    def _apply_event(self, event: dict[str, Any]) -> None:
        etype = event.get("event_type", "")
        payload = event.get("payload", {})

        if etype == "intel.memory.created":
            record = MemoryRecord(
                memory_id=payload["memory_id"],
                memory_type=MemoryType(payload["memory_type"]),
                content=payload["content"],
                context=payload.get("context", {}),
                confidence=payload.get("confidence", 0.5),
                source=payload.get("source", ""),
                source_id=payload.get("source_id", ""),
            )
            self._records[record.memory_id] = record
            self._access_counts[record.memory_id] = 0
            self._created_at[record.memory_id] = payload.get(
                "timestamp", datetime.now(UTC).isoformat()
            )

        elif etype == "intel.memory.accessed":
            mid = payload.get("memory_id", "")
            if mid in self._access_counts:
                self._access_counts[mid] += 1

        elif etype == "intel.memory.superseded":
            mid = payload.get("memory_id", "")
            self._records.pop(mid, None)

        elif etype == "intel.memory.confidence_adjusted":
            mid = payload.get("memory_id", "")
            new_confidence = payload.get("confidence", 0.5)
            if mid in self._records:
                old = self._records[mid]
                self._records[mid] = MemoryRecord(
                    memory_id=old.memory_id,
                    memory_type=old.memory_type,
                    content=old.content,
                    context=old.context,
                    confidence=new_confidence,
                    source=old.source,
                    source_id=old.source_id,
                )

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._apply_event(event)

    async def record(
        self,
        memory_type: str,
        content: str,
        context: dict[str, Any] | None = None,
        confidence: float = 0.5,
        source: str = "",
        source_id: str = "",
    ) -> str:
        memory_id = str(ulid.new())
        self._append_event("intel.memory.created", {
            "memory_id": memory_id,
            "memory_type": memory_type,
            "content": content,
            "context": context or {},
            "confidence": confidence,
            "source": source,
            "source_id": source_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        return memory_id

    async def query(self, query: MemoryQuery) -> list[ScoredMemory]:
        candidates: list[ScoredMemory] = []
        now = datetime.now(UTC)

        for mid, record in self._records.items():
            if query.memory_type and record.memory_type != query.memory_type:
                continue
            if record.confidence < query.min_confidence:
                continue

            relevance = self._compute_relevance(record, mid, query.query_text, now)
            if relevance > 0.0:
                candidates.append(ScoredMemory(record=record, relevance=relevance))

        candidates.sort(key=lambda s: s.relevance, reverse=True)
        results = candidates[: query.limit]

        for scored in results:
            self._append_event("intel.memory.accessed", {
                "memory_id": scored.record.memory_id,
            })

        return results

    async def reinforce(self, memory_id: str) -> None:
        self._append_event("intel.memory.accessed", {"memory_id": memory_id})

    async def supersede(self, memory_id: str, reason: str = "") -> None:
        self._append_event("intel.memory.superseded", {
            "memory_id": memory_id,
            "reason": reason,
        })

    async def adjust_confidence(self, memory_id: str, confidence: float) -> None:
        self._append_event("intel.memory.confidence_adjusted", {
            "memory_id": memory_id,
            "confidence": confidence,
        })

    def _compute_relevance(
        self,
        record: MemoryRecord,
        memory_id: str,
        query_text: str,
        now: datetime,
    ) -> float:
        keyword_score = self._keyword_match(record.content, query_text)
        if keyword_score == 0.0:
            return 0.0

        created_str = self._created_at.get(memory_id, "")
        recency_score = self._recency_decay(created_str, now)
        access_score = min(self._access_counts.get(memory_id, 0) / 10.0, 1.0)

        return (
            keyword_score * 0.45
            + recency_score * 0.25
            + record.confidence * 0.20
            + access_score * 0.10
        )

    def _keyword_match(self, content: str, query: str) -> float:
        if not query:
            return 0.5
        content_lower = content.lower()
        query_terms = query.lower().split()
        if not query_terms:
            return 0.5
        matches = sum(1 for term in query_terms if term in content_lower)
        return matches / len(query_terms)

    def _recency_decay(self, created_str: str, now: datetime) -> float:
        if not created_str:
            return 0.5
        try:
            created = datetime.fromisoformat(created_str)
            age_days = (now - created).total_seconds() / 86400.0
            import math
            half_life = 30.0
            return math.exp(-age_days / half_life)
        except (ValueError, TypeError):
            return 0.5

    @property
    def record_count(self) -> int:
        return len(self._records)
