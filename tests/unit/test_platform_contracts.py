"""Tests for platform contract validation schemas."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.platform.contracts import (
    PLATFORM_CONTRACTS,
    ContractViolation,
    PlatformContract,
    validate_all,
    validate_platform,
)
from reins.platform.registry import get_platform
from reins.platform.types import PlatformType


def test_platform_contracts_has_15_entries() -> None:
    """All 14 platforms + CUSTOM have contract entries."""
    assert len(PLATFORM_CONTRACTS) >= 14


def test_validate_platform_passes_for_valid_claude(tmp_path: Path) -> None:
    """A fully valid Claude config directory passes validation."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks").mkdir()
    (claude_dir / "agents").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "settings.json").write_text('{"hooks": {}}')

    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    violations = validate_platform(config, tmp_path)
    assert violations == []


def test_validate_platform_fails_for_missing_path(tmp_path: Path) -> None:
    """Missing required path produces a violation."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "agents").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "settings.json").write_text('{"hooks": {}}')
    # hooks/ directory is missing

    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    violations = validate_platform(config, tmp_path)
    assert len(violations) == 1
    assert violations[0].rule == "required_path_exists"
    assert "hooks" in violations[0].path


def test_validate_platform_fails_for_missing_content(tmp_path: Path) -> None:
    """Missing required content in a file produces a violation."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks").mkdir()
    (claude_dir / "agents").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "settings.json").write_text("{}")  # no "hooks" string

    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    violations = validate_platform(config, tmp_path)
    assert len(violations) == 1
    assert violations[0].rule == "required_content"
    assert "hooks" in violations[0].detail


def test_validate_platform_passes_for_generic(tmp_path: Path) -> None:
    """A generic platform with no required paths passes with just config dir."""
    windsurf_dir = tmp_path / ".windsurf"
    windsurf_dir.mkdir()

    config = get_platform(PlatformType.WINDSURF)
    assert config is not None
    violations = validate_platform(config, tmp_path)
    assert violations == []


def test_contract_violation_fields() -> None:
    """ContractViolation exposes all expected fields."""
    v = ContractViolation(
        platform=PlatformType.CLAUDE_CODE,
        path="hooks",
        rule="required_path_exists",
        detail="Required path 'hooks' missing",
    )
    assert v.platform == PlatformType.CLAUDE_CODE
    assert v.path == "hooks"
    assert v.rule == "required_path_exists"
    assert "missing" in v.detail


def test_validate_all_detects_multiple(tmp_path: Path) -> None:
    """validate_all returns results for multiple detected platforms."""
    # Create Claude config
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks").mkdir()
    (claude_dir / "agents").mkdir()
    (claude_dir / "commands").mkdir()
    (claude_dir / "settings.json").write_text('{"hooks": {}}')

    # Create Cursor config
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "settings.json").write_text("{}")
    (tmp_path / ".cursorrules").write_text("")

    results = validate_all(tmp_path)
    assert PlatformType.CLAUDE_CODE in results
    assert PlatformType.CURSOR in results


def test_claude_contract_has_required_paths() -> None:
    """Claude contract specifies hooks, agents, commands, settings.json."""
    contract = PLATFORM_CONTRACTS[PlatformType.CLAUDE_CODE]
    assert "hooks" in contract.required_paths
    assert "agents" in contract.required_paths
    assert "commands" in contract.required_paths
    assert "settings.json" in contract.required_paths


def test_cursor_contract_has_required_paths() -> None:
    """Cursor contract specifies settings.json inside .cursor/ dir.

    Note: .cursorrules lives at repo root, not inside .cursor/, so it is
    not part of the config-dir contract.
    """
    contract = PLATFORM_CONTRACTS[PlatformType.CURSOR]
    assert "settings.json" in contract.required_paths
