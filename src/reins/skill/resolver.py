from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from reins.skill.catalog import SkillDescriptor, SkillRegistry


class TrustTier(str, Enum):
    """Three-tier trust model for skills."""

    TRUSTED = "trusted"  # Tier 0-1: Fully trusted, auto-approved
    REVIEWED = "reviewed"  # Tier 2: Reviewed, requires approval
    UNTRUSTED = "untrusted"  # Tier 3+: Untrusted, blocked or requires strict approval


@dataclass(frozen=True)
class ResolvedSkill:
    descriptor: SkillDescriptor
    relevance: float
    estimated_cost: int
    trust_classification: TrustTier


class SkillResolver:
    def __init__(
        self,
        registry: SkillRegistry,
        available_tools: set[str] | None = None,
        available_protocols: set[str] | None = None,
        min_trust_tier: int = 0,
        max_trust_tier: int = 2,
        enforce_trust_model: bool = True,
    ) -> None:
        self.registry = registry
        self.available_tools = available_tools or set()
        self.available_protocols = available_protocols or set()
        self.min_trust_tier = min_trust_tier
        self.max_trust_tier = max_trust_tier
        self.enforce_trust_model = enforce_trust_model
        self._activated: set[str] = set()

    def classify_trust(self, trust_tier: int) -> TrustTier:
        """Classify a numeric trust tier into the three-tier model."""
        if trust_tier <= 1:
            return TrustTier.TRUSTED
        elif trust_tier == 2:
            return TrustTier.REVIEWED
        else:
            return TrustTier.UNTRUSTED

    async def resolve(
        self, query: str, tags: list[str] | None = None, top_k: int = 5
    ) -> list[SkillDescriptor]:
        candidates = await self.metadata_search(query, tags or [])
        ranked = self.semantic_relevance(query, candidates)
        constrained = self.constraint_filter(ranked)
        trusted = self.trust_filter(constrained)
        costed = self.cost_estimation(trusted)
        return [item.descriptor for item in self.top_k_manifest_load(costed, top_k)]

    async def metadata_search(
        self, query: str, tags: list[str]
    ) -> list[SkillDescriptor]:
        return await self.registry.search(query, tags)

    def semantic_relevance(
        self, query: str, candidates: list[SkillDescriptor]
    ) -> list[ResolvedSkill]:
        query_terms = Counter(term.lower() for term in query.split() if term)
        resolved: list[ResolvedSkill] = []
        for descriptor in candidates:
            haystack = Counter(
                term.lower()
                for term in " ".join(
                    [
                        descriptor.name,
                        descriptor.description,
                        *descriptor.tags,
                        *descriptor.outputs,
                    ]
                ).split()
            )
            overlap = sum((query_terms & haystack).values())
            trust_classification = self.classify_trust(descriptor.trust_tier)
            resolved.append(
                ResolvedSkill(descriptor, float(overlap), 0, trust_classification)
            )
        return sorted(resolved, key=lambda item: item.relevance, reverse=True)

    def constraint_filter(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        def allowed(item: ResolvedSkill) -> bool:
            tools = set(item.descriptor.required_tools).issubset(self.available_tools)
            protocols = set(item.descriptor.required_protocols).issubset(
                self.available_protocols
            )
            return tools and protocols

        return [item for item in candidates if allowed(item)]

    def trust_filter(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        """Filter skills based on trust tier constraints.

        If enforce_trust_model is True:
        - Only allows skills within [min_trust_tier, max_trust_tier] range
        - UNTRUSTED skills (tier 3+) are blocked by default

        If enforce_trust_model is False:
        - Only applies min_trust_tier filter (backward compatible)
        """
        if not self.enforce_trust_model:
            # Legacy behavior: only check minimum
            return [
                item
                for item in candidates
                if item.descriptor.trust_tier >= self.min_trust_tier
            ]

        # New behavior: enforce trust model
        filtered: list[ResolvedSkill] = []
        for item in candidates:
            tier = item.descriptor.trust_tier

            # Check if within allowed range
            if tier < self.min_trust_tier or tier > self.max_trust_tier:
                continue

            # Block UNTRUSTED by default unless explicitly allowed
            if (
                item.trust_classification == TrustTier.UNTRUSTED
                and self.max_trust_tier < 3
            ):
                continue

            filtered.append(item)

        return filtered

    def cost_estimation(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        costed: list[ResolvedSkill] = []
        for item in candidates:
            cost = (
                len(item.descriptor.required_tools)
                + len(item.descriptor.required_protocols)
                + len(item.descriptor.dependencies)
            )
            costed.append(
                ResolvedSkill(
                    item.descriptor, item.relevance, cost, item.trust_classification
                )
            )
        return costed

    def top_k_manifest_load(
        self, candidates: list[ResolvedSkill], top_k: int
    ) -> list[ResolvedSkill]:
        ordered = sorted(
            candidates, key=lambda item: (-item.relevance, item.estimated_cost)
        )
        return ordered[:top_k]

    def requires_approval(self, skill_id: str) -> bool:
        """Check if a skill requires approval based on trust tier.

        Returns:
            True if skill is REVIEWED or UNTRUSTED and requires approval
            False if skill is TRUSTED and can be auto-approved
        """
        # This is a synchronous wrapper - in real usage, call the async version
        import asyncio

        return asyncio.run(self.requires_approval_async(skill_id))

    async def requires_approval_async(self, skill_id: str) -> bool:
        """Async version of requires_approval."""
        descriptor = await self.registry.lookup(skill_id)
        if descriptor is None:
            return True  # Unknown skills require approval

        trust_classification = self.classify_trust(descriptor.trust_tier)

        if trust_classification == TrustTier.TRUSTED:
            return False  # Auto-approved
        elif trust_classification == TrustTier.REVIEWED:
            return True  # Requires approval
        else:  # UNTRUSTED
            return True  # Requires strict approval

    def get_trust_classification(self, skill_id: str) -> TrustTier | None:
        """Get the trust classification for a skill.

        Returns None if skill not found.
        """
        import asyncio

        return asyncio.run(self.get_trust_classification_async(skill_id))

    async def get_trust_classification_async(self, skill_id: str) -> TrustTier | None:
        """Async version of get_trust_classification."""
        descriptor = await self.registry.lookup(skill_id)
        if descriptor is None:
            return None

        return self.classify_trust(descriptor.trust_tier)

    async def activate(self, skill_id: str) -> SkillDescriptor | None:
        descriptor = await self.registry.lookup(skill_id)
        if descriptor is not None:
            self._activated.add(skill_id)
        return descriptor
