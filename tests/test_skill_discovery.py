"""Tests for SKILL.md discovery and parsing."""

import pytest
from pathlib import Path

from reins.skill.discovery import SkillDiscovery


@pytest.fixture
def skill_dir(tmp_path):
    """Create a temporary directory with test SKILL.md files."""
    # Create skill1
    skill1_dir = tmp_path / "skills" / "skill1"
    skill1_dir.mkdir(parents=True)
    (skill1_dir / "SKILL.md").write_text(
        """# Data Analysis Skill

Analyzes data and generates insights.

## Metadata

- **skill_id**: data-analysis
- **version**: 1.0.0
- **tags**: data, analysis, insights
- **required_tools**: pandas, numpy
- **trust_tier**: 1
- **capabilities**: fs.read, exec.shell.sandboxed

## Usage

Use this skill to analyze datasets.
"""
    )

    # Create skill2
    skill2_dir = tmp_path / "skills" / "skill2"
    skill2_dir.mkdir(parents=True)
    (skill2_dir / "SKILL.md").write_text(
        """# Code Review Skill

Reviews code for quality and security issues.

## Metadata

- **skill_id**: code-review
- **version**: 2.0.0
- **tags**: code, review, security
- **required_tools**: ast-parser
- **required_protocols**: git
- **trust_tier**: 2
- **capabilities**: fs.read
- **dependencies**: linter-skill

## Usage

Use this skill to review code changes.
"""
    )

    # Create skill3 (minimal metadata)
    skill3_dir = tmp_path / "skills" / "skill3"
    skill3_dir.mkdir(parents=True)
    (skill3_dir / "SKILL.md").write_text(
        """# Simple Skill

A simple skill with minimal metadata.

## Metadata

- **version**: 0.1.0

## Usage

Basic usage.
"""
    )

    return tmp_path


def test_discover_skill_files(skill_dir):
    """Test discovering SKILL.md files."""
    discovery = SkillDiscovery([skill_dir / "skills"])
    skill_files = discovery.discover()

    assert len(skill_files) == 3
    skill_names = {f.parent.name for f in skill_files}
    assert skill_names == {"skill1", "skill2", "skill3"}


def test_discover_multiple_search_paths(tmp_path):
    """Test discovering from multiple search paths."""
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()

    (path1 / "SKILL.md").write_text("# Skill 1\n\nDescription")
    (path2 / "SKILL.md").write_text("# Skill 2\n\nDescription")

    discovery = SkillDiscovery([path1, path2])
    skill_files = discovery.discover()

    assert len(skill_files) == 2


def test_discover_nonexistent_path():
    """Test discovering from nonexistent path."""
    discovery = SkillDiscovery([Path("/nonexistent/path")])
    skill_files = discovery.discover()

    assert len(skill_files) == 0


def test_parse_skill_manifest(skill_dir):
    """Test parsing a SKILL.md file."""
    skill_file = skill_dir / "skills" / "skill1" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)

    assert manifest is not None
    assert manifest.skill_id == "data-analysis"
    assert manifest.name == "Data Analysis Skill"
    assert "Analyzes data" in manifest.description
    assert manifest.version == "1.0.0"
    assert manifest.source_path == skill_file


def test_parse_metadata_section(skill_dir):
    """Test parsing metadata from SKILL.md."""
    skill_file = skill_dir / "skills" / "skill1" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)

    assert manifest is not None
    assert manifest.metadata["skill_id"] == "data-analysis"
    assert manifest.metadata["version"] == "1.0.0"
    assert manifest.metadata["tags"] == ["data", "analysis", "insights"]
    assert manifest.metadata["required_tools"] == ["pandas", "numpy"]
    assert manifest.metadata["trust_tier"] == "1"
    assert manifest.metadata["capabilities"] == ["fs.read", "exec.shell.sandboxed"]


def test_parse_skill_with_dependencies(skill_dir):
    """Test parsing skill with dependencies."""
    skill_file = skill_dir / "skills" / "skill2" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)

    assert manifest is not None
    # Single values are stored as strings, not lists
    assert manifest.metadata["dependencies"] == "linter-skill"
    assert manifest.metadata["required_protocols"] == "git"


def test_parse_skill_minimal_metadata(skill_dir):
    """Test parsing skill with minimal metadata."""
    skill_file = skill_dir / "skills" / "skill3" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)

    assert manifest is not None
    assert manifest.skill_id == "skill3"  # Derived from directory name
    assert manifest.name == "Simple Skill"
    assert manifest.version == "0.1.0"


def test_parse_nonexistent_file():
    """Test parsing nonexistent file."""
    discovery = SkillDiscovery([])
    manifest = discovery.parse(Path("/nonexistent/SKILL.md"))

    assert manifest is None


def test_parse_invalid_format(tmp_path):
    """Test parsing file with invalid format."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("Not a valid SKILL.md format")

    discovery = SkillDiscovery([])
    manifest = discovery.parse(skill_file)

    # Should return None for files without proper heading
    assert manifest is None


def test_to_descriptor(skill_dir):
    """Test converting manifest to descriptor."""
    skill_file = skill_dir / "skills" / "skill1" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)
    assert manifest is not None

    descriptor = discovery.to_descriptor(manifest)

    assert descriptor.skill_id == "data-analysis"
    assert descriptor.name == "Data Analysis Skill"
    assert "Analyzes data" in descriptor.description
    assert descriptor.version == "1.0.0"
    assert descriptor.tags == ["data", "analysis", "insights"]
    assert descriptor.required_tools == ["pandas", "numpy"]
    assert descriptor.trust_tier == 1
    assert descriptor.allowed_capabilities == ["fs.read", "exec.shell.sandboxed"]
    assert len(descriptor.manifest_hash) == 16


def test_to_descriptor_with_dependencies(skill_dir):
    """Test converting manifest with dependencies to descriptor."""
    skill_file = skill_dir / "skills" / "skill2" / "SKILL.md"
    discovery = SkillDiscovery([])

    manifest = discovery.parse(skill_file)
    assert manifest is not None

    descriptor = discovery.to_descriptor(manifest)

    assert descriptor.dependencies == ["linter-skill"]
    assert descriptor.required_protocols == ["git"]
    assert descriptor.trust_tier == 2


def test_scan_and_parse(skill_dir):
    """Test scanning and parsing all skills."""
    discovery = SkillDiscovery([skill_dir / "skills"])
    descriptors = discovery.scan_and_parse()

    assert len(descriptors) == 3

    skill_ids = {d.skill_id for d in descriptors}
    assert "data-analysis" in skill_ids
    assert "code-review" in skill_ids
    assert "skill3" in skill_ids


def test_scan_and_parse_empty_directory(tmp_path):
    """Test scanning empty directory."""
    discovery = SkillDiscovery([tmp_path])
    descriptors = discovery.scan_and_parse()

    assert len(descriptors) == 0


def test_manifest_hash_uniqueness(skill_dir):
    """Test that different manifests have different hashes."""
    discovery = SkillDiscovery([skill_dir / "skills"])

    skill1 = discovery.parse(skill_dir / "skills" / "skill1" / "SKILL.md")
    skill2 = discovery.parse(skill_dir / "skills" / "skill2" / "SKILL.md")

    assert skill1 is not None
    assert skill2 is not None

    desc1 = discovery.to_descriptor(skill1)
    desc2 = discovery.to_descriptor(skill2)

    assert desc1.manifest_hash != desc2.manifest_hash


def test_parse_metadata_with_single_values(tmp_path):
    """Test parsing metadata with single values (not lists)."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """# Test Skill

Description

## Metadata

- **skill_id**: test-skill
- **version**: 1.0.0
- **tags**: single-tag
- **trust_tier**: 3
"""
    )

    discovery = SkillDiscovery([])
    manifest = discovery.parse(skill_file)

    assert manifest is not None
    descriptor = discovery.to_descriptor(manifest)

    assert descriptor.tags == ["single-tag"]
    assert descriptor.trust_tier == 3


def test_parse_metadata_with_empty_lists(tmp_path):
    """Test parsing metadata with empty or missing fields."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """# Test Skill

Description

## Metadata

- **skill_id**: test-skill
- **version**: 1.0.0
"""
    )

    discovery = SkillDiscovery([])
    manifest = discovery.parse(skill_file)

    assert manifest is not None
    descriptor = discovery.to_descriptor(manifest)

    assert descriptor.tags == []
    assert descriptor.required_tools == []
    assert descriptor.dependencies == []
    assert descriptor.trust_tier == 0


def test_nested_skill_directories(tmp_path):
    """Test discovering skills in nested directories."""
    nested = tmp_path / "level1" / "level2" / "skill"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("# Nested Skill\n\nDescription")

    discovery = SkillDiscovery([tmp_path])
    skill_files = discovery.discover()

    assert len(skill_files) == 1
    assert skill_files[0].parent.name == "skill"
