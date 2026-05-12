"""Tests for platform descriptors and descriptor engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.platform.descriptors import (
    PLATFORM_DESCRIPTORS,
    FileMapping,
    HookDescriptor,
    PlatformDescriptor,
    get_descriptor,
)
from reins.platform.engine import DescriptorEngine
from reins.platform.registry import get_platform
from reins.platform.types import PlatformType


def test_platform_descriptors_has_14_entries() -> None:
    """All non-CUSTOM platforms have a descriptor."""
    assert len(PLATFORM_DESCRIPTORS) == 14
    assert PlatformType.CUSTOM not in PLATFORM_DESCRIPTORS


def test_get_descriptor_claude_code() -> None:
    """Claude Code descriptor is retrievable and well-formed."""
    desc = get_descriptor(PlatformType.CLAUDE_CODE)
    assert desc is not None
    assert desc.platform_type == PlatformType.CLAUDE_CODE
    assert len(desc.files) == 2
    assert len(desc.hooks) == 2


def test_get_descriptor_returns_none_for_custom() -> None:
    """CUSTOM platform has no descriptor."""
    assert get_descriptor(PlatformType.CUSTOM) is None


def test_claude_descriptor_has_settings_file() -> None:
    desc = get_descriptor(PlatformType.CLAUDE_CODE)
    assert desc is not None
    assert desc.settings_file == "settings.json"


def test_claude_descriptor_has_hooks() -> None:
    desc = get_descriptor(PlatformType.CLAUDE_CODE)
    assert desc is not None
    hook_names = [h.name for h in desc.hooks]
    assert "session-start" in hook_names
    assert "inject-subagent-context" in hook_names
    for hook in desc.hooks:
        assert hook.language == "python"


def test_cursor_descriptor_has_files_no_hooks() -> None:
    desc = get_descriptor(PlatformType.CURSOR)
    assert desc is not None
    assert len(desc.files) == 2
    assert len(desc.hooks) == 0
    targets = [f.target_path for f in desc.files]
    assert ".cursorrules" in targets
    assert "settings.json" in targets


def test_codex_descriptor_has_hooks_and_subdirs() -> None:
    desc = get_descriptor(PlatformType.CODEX)
    assert desc is not None
    assert len(desc.files) == 3
    assert len(desc.hooks) == 1
    assert desc.hooks[0].name == "session-start"
    assert "hooks" in desc.subdirs
    assert "agents" in desc.subdirs
    assert desc.settings_file == "config.yaml"


def test_engine_creates_config_dir(tmp_path: Path) -> None:
    """Engine creates the config directory even for empty descriptors."""
    config = get_platform(PlatformType.WINDSURF)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    results = engine.generate(config)
    assert results == []
    assert (tmp_path / config.config_dir).is_dir()


def test_engine_check_staleness_empty_for_fresh(tmp_path: Path) -> None:
    """Freshly generated configs report no staleness."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    results = engine.generate(config)
    assert len(results) > 0
    stale = engine.check_staleness(config)
    assert stale == []


def test_engine_check_staleness_detects_missing(tmp_path: Path) -> None:
    """Missing files are detected as stale."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    engine.generate(config)
    # Remove a generated file
    target = tmp_path / config.config_dir / "settings.json"
    target.unlink()
    stale = engine.check_staleness(config)
    assert ("settings.json", "missing") in stale


def test_engine_check_staleness_detects_customized(tmp_path: Path) -> None:
    """User-modified files are detected as customized."""
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    engine.generate(config)
    target = tmp_path / config.config_dir / "settings.json"
    target.write_text("user edited content", encoding="utf-8")
    stale = engine.check_staleness(config)
    assert ("settings.json", "customized") in stale
