"""Tests for skill trust tier enforcement."""

import pytest
from pathlib import Path

from reins.skill.catalog import SkillDescriptor, SkillRegistry
from reins.skill.resolver import SkillResolver, TrustTier


@pytest.fixture
def skill_registry(tmp_path):
    """Create a registry with skills at different trust tiers."""
    registry_file = tmp_path / "skills.jsonl"

    # Create skills with different trust tiers
    skills = [
        SkillDescriptor(
            skill_id="trusted-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash1",
            name="Trusted Skill",
            description="A trusted skill",
            trust_tier=0,
        ),
        SkillDescriptor(
            skill_id="trusted-skill-2",
            source="test",
            version="1.0.0",
            manifest_hash="hash2",
            name="Trusted Skill 2",
            description="Another trusted skill",
            trust_tier=1,
        ),
        SkillDescriptor(
            skill_id="reviewed-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash3",
            name="Reviewed Skill",
            description="A reviewed skill",
            trust_tier=2,
        ),
        SkillDescriptor(
            skill_id="untrusted-skill",
            source="test",
            version="1.0.0",
            manifest_hash="hash4",
            name="Untrusted Skill",
            description="An untrusted skill",
            trust_tier=3,
        ),
        SkillDescriptor(
            skill_id="untrusted-skill-2",
            source="test",
            version="1.0.0",
            manifest_hash="hash5",
            name="Untrusted Skill 2",
            description="Another untrusted skill",
            trust_tier=4,
        ),
    ]

    # Write to registry file
    import json

    with open(registry_file, "w") as f:
        for skill in skills:
            f.write(json.dumps(skill.__dict__) + "\n")

    return SkillRegistry(registry_file)


def test_trust_tier_classification():
    """Test trust tier classification."""
    resolver = SkillResolver(SkillRegistry(Path("/tmp/nonexistent")))

    assert resolver.classify_trust(0) == TrustTier.TRUSTED
    assert resolver.classify_trust(1) == TrustTier.TRUSTED
    assert resolver.classify_trust(2) == TrustTier.REVIEWED
    assert resolver.classify_trust(3) == TrustTier.UNTRUSTED
    assert resolver.classify_trust(4) == TrustTier.UNTRUSTED
    assert resolver.classify_trust(10) == TrustTier.UNTRUSTED


@pytest.mark.asyncio
async def test_trust_filter_with_enforcement(skill_registry):
    """Test trust filtering with enforcement enabled."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=0,
        max_trust_tier=2,
        enforce_trust_model=True,
    )

    # Get all skills
    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)

    # Apply trust filter
    filtered = resolver.trust_filter(resolved)

    # Should only include trusted and reviewed (tier 0-2)
    skill_ids = {item.descriptor.skill_id for item in filtered}
    assert "trusted-skill" in skill_ids
    assert "trusted-skill-2" in skill_ids
    assert "reviewed-skill" in skill_ids
    assert "untrusted-skill" not in skill_ids
    assert "untrusted-skill-2" not in skill_ids


@pytest.mark.asyncio
async def test_trust_filter_without_enforcement(skill_registry):
    """Test trust filtering with enforcement disabled (legacy mode)."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=0,
        enforce_trust_model=False,
    )

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)
    filtered = resolver.trust_filter(resolved)

    # Should include all skills (legacy behavior)
    assert len(filtered) == 5


@pytest.mark.asyncio
async def test_trust_filter_only_trusted(skill_registry):
    """Test filtering to only allow trusted skills."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=0,
        max_trust_tier=1,
        enforce_trust_model=True,
    )

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)
    filtered = resolver.trust_filter(resolved)

    # Should only include tier 0-1
    skill_ids = {item.descriptor.skill_id for item in filtered}
    assert "trusted-skill" in skill_ids
    assert "trusted-skill-2" in skill_ids
    assert "reviewed-skill" not in skill_ids
    assert "untrusted-skill" not in skill_ids


@pytest.mark.asyncio
async def test_trust_filter_allow_untrusted(skill_registry):
    """Test allowing untrusted skills explicitly."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=0,
        max_trust_tier=4,
        enforce_trust_model=True,
    )

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)
    filtered = resolver.trust_filter(resolved)

    # Should include all skills
    assert len(filtered) == 5


@pytest.mark.asyncio
async def test_requires_approval_trusted(skill_registry):
    """Test that trusted skills don't require approval."""
    resolver = SkillResolver(skill_registry)

    requires = await resolver.requires_approval_async("trusted-skill")
    assert requires is False

    requires = await resolver.requires_approval_async("trusted-skill-2")
    assert requires is False


@pytest.mark.asyncio
async def test_requires_approval_reviewed(skill_registry):
    """Test that reviewed skills require approval."""
    resolver = SkillResolver(skill_registry)

    requires = await resolver.requires_approval_async("reviewed-skill")
    assert requires is True


@pytest.mark.asyncio
async def test_requires_approval_untrusted(skill_registry):
    """Test that untrusted skills require approval."""
    resolver = SkillResolver(skill_registry)

    requires = await resolver.requires_approval_async("untrusted-skill")
    assert requires is True

    requires = await resolver.requires_approval_async("untrusted-skill-2")
    assert requires is True


@pytest.mark.asyncio
async def test_requires_approval_unknown_skill(skill_registry):
    """Test that unknown skills require approval."""
    resolver = SkillResolver(skill_registry)

    requires = await resolver.requires_approval_async("nonexistent-skill")
    assert requires is True


@pytest.mark.asyncio
async def test_get_trust_classification(skill_registry):
    """Test getting trust classification for skills."""
    resolver = SkillResolver(skill_registry)

    classification = await resolver.get_trust_classification_async("trusted-skill")
    assert classification == TrustTier.TRUSTED

    classification = await resolver.get_trust_classification_async("reviewed-skill")
    assert classification == TrustTier.REVIEWED

    classification = await resolver.get_trust_classification_async("untrusted-skill")
    assert classification == TrustTier.UNTRUSTED

    classification = await resolver.get_trust_classification_async("nonexistent")
    assert classification is None


@pytest.mark.asyncio
async def test_resolve_with_trust_enforcement(skill_registry):
    """Test full resolve flow with trust enforcement."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=0,
        max_trust_tier=2,
        enforce_trust_model=True,
    )

    results = await resolver.resolve("skill", top_k=10)

    # Should only return trusted and reviewed skills
    skill_ids = {d.skill_id for d in results}
    assert "trusted-skill" in skill_ids or "trusted-skill-2" in skill_ids
    assert "untrusted-skill" not in skill_ids
    assert "untrusted-skill-2" not in skill_ids


@pytest.mark.asyncio
async def test_resolved_skill_includes_trust_classification(skill_registry):
    """Test that ResolvedSkill includes trust classification."""
    resolver = SkillResolver(skill_registry)

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)

    # Check that each resolved skill has trust classification
    for item in resolved:
        assert isinstance(item.trust_classification, TrustTier)

    # Find specific skills and check their classification
    trusted = next(r for r in resolved if r.descriptor.skill_id == "trusted-skill")
    assert trusted.trust_classification == TrustTier.TRUSTED

    reviewed = next(r for r in resolved if r.descriptor.skill_id == "reviewed-skill")
    assert reviewed.trust_classification == TrustTier.REVIEWED

    untrusted = next(r for r in resolved if r.descriptor.skill_id == "untrusted-skill")
    assert untrusted.trust_classification == TrustTier.UNTRUSTED


@pytest.mark.asyncio
async def test_trust_filter_min_tier_boundary(skill_registry):
    """Test trust filter with min_trust_tier boundary."""
    resolver = SkillResolver(
        skill_registry,
        min_trust_tier=2,
        max_trust_tier=3,
        enforce_trust_model=True,
    )

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)
    filtered = resolver.trust_filter(resolved)

    # Should only include tier 2-3
    skill_ids = {item.descriptor.skill_id for item in filtered}
    assert "trusted-skill" not in skill_ids
    assert "trusted-skill-2" not in skill_ids
    assert "reviewed-skill" in skill_ids
    assert "untrusted-skill" in skill_ids
    assert "untrusted-skill-2" not in skill_ids  # tier 4 is above max


@pytest.mark.asyncio
async def test_cost_estimation_preserves_trust_classification(skill_registry):
    """Test that cost estimation preserves trust classification."""
    resolver = SkillResolver(skill_registry)

    all_skills = await skill_registry.search("skill", [])
    resolved = resolver.semantic_relevance("skill", all_skills)
    costed = resolver.cost_estimation(resolved)

    # Check that trust classification is preserved
    for item in costed:
        assert isinstance(item.trust_classification, TrustTier)
