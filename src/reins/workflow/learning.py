"""Learning extraction and spec-update flow.

Extracts structured learnings from retrospectives, scores confidence,
and proposes spec updates for high-confidence learnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import ulid

from reins.workflow.break_loop import Retrospective
from reins.workflow.retrospective import Learning, RetrospectiveStore


class LearningCategory(str, Enum):
    """Categories for extracted learnings."""

    pattern = "pattern"
    anti_pattern = "anti_pattern"
    constraint = "constraint"
    workaround = "workaround"
    optimization = "optimization"


@dataclass(frozen=True)
class SpecUpdateProposal:
    """Proposal to update or create a spec based on a learning."""

    learning_id: str
    target_spec_id: str | None
    proposed_content: str
    applicability: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.7
    reason: str = ""


class LearningExtractor:
    """Extracts structured learnings from retrospectives."""

    def __init__(self, store: RetrospectiveStore) -> None:
        self._store = store

    def extract_from_retrospective(self, retro: Retrospective) -> list[Learning]:
        """Parse retrospective learnings into structured Learning objects."""
        results: list[Learning] = []
        retro_id = str(ulid.new())

        for text in retro.learnings:
            category = self._categorize(text, retro)
            confidence = self._compute_confidence(retro)
            applicability = self._infer_applicability(retro)

            learning = Learning(
                learning_id=str(ulid.new()),
                source_retrospective_id=retro_id,
                category=category.value,
                summary=text[:120],
                detail=text,
                applicability=applicability,
                confidence=confidence,
            )
            results.append(learning)

        return results

    def propose_spec_updates(
        self, learnings: list[Learning], min_confidence: float = 0.7
    ) -> list[SpecUpdateProposal]:
        """For high-confidence learnings, propose spec updates."""
        proposals: list[SpecUpdateProposal] = []
        for learning in learnings:
            if not self.should_promote_to_spec(learning, min_confidence):
                continue
            spec_type = self._map_category_to_spec_type(learning.category)
            proposal = SpecUpdateProposal(
                learning_id=learning.learning_id,
                target_spec_id=None,
                proposed_content=f"[{spec_type}] {learning.summary}\n\n{learning.detail}",
                applicability=learning.applicability,
                confidence=learning.confidence,
                reason=f"High-confidence {learning.category} learning from retrospective",
            )
            proposals.append(proposal)
        return proposals

    def should_promote_to_spec(
        self, learning: Learning, min_confidence: float = 0.7
    ) -> bool:
        """Return True if learning should be promoted to a spec."""
        return learning.confidence >= min_confidence and bool(learning.applicability)

    def _categorize(self, text: str, retro: Retrospective) -> LearningCategory:
        """Assign category based on content heuristics."""
        lower = text.lower()
        if any(w in lower for w in ("avoid", "don't", "never", "wrong", "fail")):
            return LearningCategory.anti_pattern
        if any(w in lower for w in ("workaround", "hack", "bypass", "instead")):
            return LearningCategory.workaround
        if any(w in lower for w in ("must", "require", "always", "constraint")):
            return LearningCategory.constraint
        if any(w in lower for w in ("faster", "optimize", "performance", "cache")):
            return LearningCategory.optimization
        # Default: if retro had failures, likely a pattern learned from failure
        if retro.failure_reasons:
            return LearningCategory.pattern
        return LearningCategory.pattern

    def _compute_confidence(self, retro: Retrospective) -> float:
        """Set confidence based on repetition count from the trigger pattern."""
        count = retro.trigger.count
        if count >= 5:
            return 0.9
        if count >= 3:
            return 0.7
        return 0.5

    def _infer_applicability(self, retro: Retrospective) -> dict[str, str]:
        """Infer applicability from retrospective context."""
        applicability: dict[str, str] = {}
        if retro.task_id:
            applicability["task_type"] = "general"
        return applicability

    def _map_category_to_spec_type(self, category: str) -> str:
        """Map learning category to spec type."""
        mapping = {
            "anti_pattern": "constraint",
            "constraint": "constraint",
            "pattern": "guidance",
            "workaround": "guidance",
            "optimization": "guidance",
        }
        return mapping.get(category, "guidance")


class LearningFlow:
    """Full pipeline: retrospective -> learnings -> spec proposals."""

    def __init__(self, store: RetrospectiveStore, extractor: LearningExtractor) -> None:
        self._store = store
        self._extractor = extractor
        self._pending_proposals: list[SpecUpdateProposal] = []

    def process_retrospective(self, retro: Retrospective) -> list[SpecUpdateProposal]:
        """Full pipeline: save retro -> extract learnings -> save -> propose."""
        self._store.save_retrospective(retro)
        learnings = self._extractor.extract_from_retrospective(retro)
        for learning in learnings:
            self._store.save_learning(learning)
        proposals = self._extractor.propose_spec_updates(learnings)
        self._pending_proposals.extend(proposals)
        return proposals

    def get_pending_proposals(self) -> list[SpecUpdateProposal]:
        """Return proposals that haven't been applied yet."""
        return list(self._pending_proposals)
