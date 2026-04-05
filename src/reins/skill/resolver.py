from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from reins.skill.catalog import SkillDescriptor, SkillRegistry


@dataclass(frozen=True)
class ResolvedSkill:
    descriptor: SkillDescriptor
    relevance: float
    estimated_cost: int


class SkillResolver:
    def __init__(
        self,
        registry: SkillRegistry,
        available_tools: set[str] | None = None,
        available_protocols: set[str] | None = None,
        min_trust_tier: int = 0,
    ) -> None:
        self.registry = registry
        self.available_tools = available_tools or set()
        self.available_protocols = available_protocols or set()
        self.min_trust_tier = min_trust_tier
        self._activated: set[str] = set()

    async def resolve(self, query: str, tags: list[str] | None = None, top_k: int = 5) -> list[SkillDescriptor]:
        candidates = await self.metadata_search(query, tags or [])
        ranked = self.semantic_relevance(query, candidates)
        constrained = self.constraint_filter(ranked)
        trusted = self.trust_filter(constrained)
        costed = self.cost_estimation(trusted)
        return [item.descriptor for item in self.top_k_manifest_load(costed, top_k)]

    async def metadata_search(self, query: str, tags: list[str]) -> list[SkillDescriptor]:
        return await self.registry.search(query, tags)

    def semantic_relevance(self, query: str, candidates: list[SkillDescriptor]) -> list[ResolvedSkill]:
        query_terms = Counter(term.lower() for term in query.split() if term)
        resolved: list[ResolvedSkill] = []
        for descriptor in candidates:
            haystack = Counter(
                term.lower()
                for term in " ".join(
                    [descriptor.name, descriptor.description, *descriptor.tags, *descriptor.outputs]
                ).split()
            )
            overlap = sum((query_terms & haystack).values())
            resolved.append(ResolvedSkill(descriptor, float(overlap), 0))
        return sorted(resolved, key=lambda item: item.relevance, reverse=True)

    def constraint_filter(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        def allowed(item: ResolvedSkill) -> bool:
            tools = set(item.descriptor.required_tools).issubset(self.available_tools)
            protocols = set(item.descriptor.required_protocols).issubset(self.available_protocols)
            return tools and protocols

        return [item for item in candidates if allowed(item)]

    def trust_filter(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        return [item for item in candidates if item.descriptor.trust_tier >= self.min_trust_tier]

    def cost_estimation(self, candidates: list[ResolvedSkill]) -> list[ResolvedSkill]:
        costed: list[ResolvedSkill] = []
        for item in candidates:
            cost = (
                len(item.descriptor.required_tools)
                + len(item.descriptor.required_protocols)
                + len(item.descriptor.dependencies)
            )
            costed.append(ResolvedSkill(item.descriptor, item.relevance, cost))
        return costed

    def top_k_manifest_load(self, candidates: list[ResolvedSkill], top_k: int) -> list[ResolvedSkill]:
        ordered = sorted(candidates, key=lambda item: (-item.relevance, item.estimated_cost))
        return ordered[:top_k]

    async def activate(self, skill_id: str) -> SkillDescriptor | None:
        descriptor = await self.registry.lookup(skill_id)
        if descriptor is not None:
            self._activated.add(skill_id)
        return descriptor
