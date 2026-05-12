from __future__ import annotations

from typing import Any

from reins.intelligence.memory.engine import MemoryEngine
from reins.intelligence.types import MemoryQuery, MemoryType, ScoredMemory
from reins.workflow.retrospective import RetrospectiveStore


CATEGORY_TO_MEMORY_TYPE: dict[str, MemoryType] = {
    "pattern": MemoryType.pattern,
    "anti_pattern": MemoryType.failure,
    "constraint": MemoryType.decision,
    "workaround": MemoryType.pattern,
    "optimization": MemoryType.pattern,
}


class RetrospectiveMemoryAdapter:
    """Reads from RetrospectiveStore and presents learnings as ScoredMemory.

    This is a live adapter (option B from Codex review): queries both
    MemoryEngine and RetrospectiveStore, translates Learning objects into
    ScoredMemory with source="retrospective".
    """

    def __init__(self, memory_engine: MemoryEngine, retro_store: RetrospectiveStore) -> None:
        self._memory = memory_engine
        self._retro = retro_store

    async def query(self, query: MemoryQuery) -> list[ScoredMemory]:
        memory_results = await self._memory.query(query)
        retro_results = self._query_retrospectives(query)

        combined = memory_results + retro_results
        combined.sort(key=lambda s: s.relevance, reverse=True)
        return combined[: query.limit]

    async def record(
        self, memory_type: str, content: str, context: dict[str, Any]
    ) -> str:
        return await self._memory.record(
            memory_type=memory_type,
            content=content,
            context=context,
            source="intelligence",
        )

    async def reinforce(self, memory_id: str) -> None:
        await self._memory.reinforce(memory_id)

    def _query_retrospectives(self, query: MemoryQuery) -> list[ScoredMemory]:
        learnings = self._retro.load_learnings()
        results: list[ScoredMemory] = []

        for learning in learnings:
            if query.memory_type:
                mapped_type = CATEGORY_TO_MEMORY_TYPE.get(learning.category)
                if mapped_type != query.memory_type:
                    continue

            if learning.confidence < query.min_confidence:
                continue

            relevance = self._score_learning(learning, query.query_text)
            if relevance <= 0.0:
                continue

            from reins.intelligence.types import MemoryRecord

            record = MemoryRecord(
                memory_id=f"retro:{learning.learning_id}",
                memory_type=CATEGORY_TO_MEMORY_TYPE.get(learning.category, MemoryType.pattern),
                content=f"{learning.summary}: {learning.detail}",
                context=learning.applicability,
                confidence=learning.confidence,
                source="retrospective",
                source_id=learning.source_retrospective_id,
            )
            results.append(ScoredMemory(record=record, relevance=relevance))

        return results

    def _score_learning(self, learning: Any, query_text: str) -> float:
        if not query_text:
            return 0.3 * learning.confidence

        text = f"{learning.summary} {learning.detail}".lower()
        terms = query_text.lower().split()
        if not terms:
            return 0.3 * learning.confidence

        matches = sum(1 for t in terms if t in text)
        keyword_score = matches / len(terms)
        if keyword_score == 0.0:
            return 0.0

        return keyword_score * 0.5 + learning.confidence * 0.3 + 0.2
