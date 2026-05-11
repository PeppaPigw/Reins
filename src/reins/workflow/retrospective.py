"""Retrospective persistence and knowledge base.

Provides durable storage for retrospectives and extracted learnings,
with query capabilities for feeding learnings back into agent context.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import ulid

from reins.workflow.break_loop import LoopPattern, Retrospective


@dataclass(frozen=True)
class Learning:
    """A structured learning extracted from a retrospective."""

    learning_id: str
    source_retrospective_id: str
    category: str  # "pattern", "anti_pattern", "constraint", "workaround", "optimization"
    summary: str
    detail: str
    applicability: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.5
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")


class RetrospectiveStore:
    """Persistent store for retrospectives and learnings using JSONL files."""

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._retro_path = self._store_path / "retrospectives.jsonl"
        self._learnings_path = self._store_path / "learnings.jsonl"

    def save_retrospective(self, retro: Retrospective) -> str:
        """Append retrospective to JSONL store, returns generated ID."""
        retro_id = str(ulid.new())
        record = {
            "retro_id": retro_id,
            "task_id": retro.task_id,
            "trigger": {
                "pattern_type": retro.trigger.pattern_type,
                "event_types": list(retro.trigger.event_types),
                "count": retro.trigger.count,
                "window_seconds": retro.trigger.window_seconds,
            },
            "timestamp": retro.timestamp,
            "context_summary": retro.context_summary,
            "attempted_actions": retro.attempted_actions,
            "failure_reasons": retro.failure_reasons,
            "learnings": retro.learnings,
            "suggested_next": retro.suggested_next,
        }
        with self._retro_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return retro_id

    def save_learning(self, learning: Learning) -> None:
        """Append learning to learnings JSONL store."""
        record = {
            "learning_id": learning.learning_id,
            "source_retrospective_id": learning.source_retrospective_id,
            "category": learning.category,
            "summary": learning.summary,
            "detail": learning.detail,
            "applicability": learning.applicability,
            "confidence": learning.confidence,
            "created_at": learning.created_at,
        }
        with self._learnings_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def load_retrospectives(self) -> list[Retrospective]:
        """Read all retrospectives from store."""
        if not self._retro_path.exists():
            return []
        results: list[Retrospective] = []
        with self._retro_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                trigger = LoopPattern(
                    pattern_type=data["trigger"]["pattern_type"],
                    event_types=tuple(data["trigger"]["event_types"]),
                    count=data["trigger"]["count"],
                    window_seconds=data["trigger"]["window_seconds"],
                )
                retro = Retrospective(
                    task_id=data["task_id"],
                    trigger=trigger,
                    timestamp=data["timestamp"],
                    context_summary=data["context_summary"],
                    attempted_actions=data.get("attempted_actions", []),
                    failure_reasons=data.get("failure_reasons", []),
                    learnings=data.get("learnings", []),
                    suggested_next=data.get("suggested_next"),
                )
                results.append(retro)
        return results

    def load_learnings(self) -> list[Learning]:
        """Read all learnings from store."""
        if not self._learnings_path.exists():
            return []
        results: list[Learning] = []
        with self._learnings_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                learning = Learning(
                    learning_id=data["learning_id"],
                    source_retrospective_id=data["source_retrospective_id"],
                    category=data["category"],
                    summary=data["summary"],
                    detail=data["detail"],
                    applicability=data.get("applicability", {}),
                    confidence=data.get("confidence", 0.5),
                    created_at=data.get("created_at", ""),
                )
                results.append(learning)
        return results

    def query_learnings(
        self,
        task_type: str | None = None,
        file_pattern: str | None = None,
        limit: int = 10,
    ) -> list[Learning]:
        """Filter learnings by applicability criteria."""
        all_learnings = self.load_learnings()
        filtered: list[Learning] = []
        for learning in all_learnings:
            if task_type and learning.applicability.get("task_type") != task_type:
                continue
            if file_pattern and learning.applicability.get("file_pattern") != file_pattern:
                continue
            filtered.append(learning)
        # Sort by confidence descending, then by created_at descending
        filtered.sort(key=lambda l: (-l.confidence, l.created_at), reverse=False)
        return filtered[:limit]

    def get_recent_learnings(self, count: int = 5) -> list[Learning]:
        """Return most recent learnings."""
        all_learnings = self.load_learnings()
        # Most recent last in file, so reverse
        return all_learnings[-count:] if all_learnings else []

    def format_learnings_for_context(self, learnings: list[Learning]) -> str:
        """Render learnings as compact context string for injection."""
        if not learnings:
            return ""
        lines: list[str] = []
        for learning in learnings:
            category_label = learning.category.replace("_", " ").title()
            lines.append(f"[{category_label}] {learning.summary}")
            if learning.detail:
                lines.append(f"  Detail: {learning.detail}")
            if learning.applicability:
                scope = ", ".join(
                    f"{k}={v}" for k, v in learning.applicability.items()
                )
                lines.append(f"  Applies to: {scope}")
            lines.append("")
        return "\n".join(lines).rstrip()
