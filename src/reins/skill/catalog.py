from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import aiofiles


@dataclass(frozen=True)
class SkillDescriptor:
    skill_id: str
    source: str
    version: str
    manifest_hash: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_protocols: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    trust_tier: int = 0
    approval_profile: str = "default"
    allowed_capabilities: list[str] = field(default_factory=list)
    evaluator_hooks: list[str] = field(default_factory=list)
    compatible_surfaces: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


class SkillRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded = False
        self._skills: dict[str, SkillDescriptor] = {}

    async def _ensure_loaded(self) -> None:
        if self._loaded or not self.path.exists():
            self._loaded = True
            return
        async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                descriptor = SkillDescriptor(**data)
                self._skills[descriptor.skill_id] = descriptor
        self._loaded = True

    async def lookup(self, skill_id: str) -> SkillDescriptor | None:
        await self._ensure_loaded()
        return self._skills.get(skill_id)

    async def search(self, query: str, tags: list[str] = []) -> list[SkillDescriptor]:
        await self._ensure_loaded()
        terms = {term.lower() for term in query.split() if term}
        wanted_tags = {tag.lower() for tag in tags}
        results: list[tuple[int, SkillDescriptor]] = []
        for descriptor in self._skills.values():
            haystack = " ".join([descriptor.name, descriptor.description, *descriptor.tags]).lower()
            tag_hits = wanted_tags.intersection({tag.lower() for tag in descriptor.tags})
            score = sum(term in haystack for term in terms) + len(tag_hits) * 2
            if score > 0 or not terms:
                results.append((score, descriptor))
        return [descriptor for _, descriptor in sorted(results, key=lambda item: item[0], reverse=True)]
