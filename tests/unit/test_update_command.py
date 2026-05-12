"""Tests for the reins update CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from reins.cli.main import app
from reins.platform.engine import DescriptorEngine
from reins.platform.registry import get_platform
from reins.platform.types import PlatformType

runner = CliRunner()


def test_update_command_importable() -> None:
    """The update command module is importable."""
    from reins.cli.commands.update import update

    assert callable(update)


def test_update_no_reins_dir_exits(tmp_path: Path) -> None:
    """Exit with error when no .reins/ directory exists."""
    with patch(
        "reins.cli.commands.update._find_reins_root", return_value=None
    ):
        result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "No .reins/ directory found" in result.output


def test_update_fresh_configs_reports_up_to_date(tmp_path: Path) -> None:
    """Freshly generated configs report up to date."""
    (tmp_path / ".reins").mkdir()
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    engine.generate(config)

    with (
        patch(
            "reins.cli.commands.update._find_reins_root",
            return_value=tmp_path,
        ),
        patch(
            "reins.cli.commands.update._resolve_platform_config",
            return_value=config,
        ),
    ):
        result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_update_dry_run_does_not_modify(tmp_path: Path) -> None:
    """Dry run shows stale files but does not modify them."""
    (tmp_path / ".reins").mkdir()
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    engine.generate(config)

    # Make a file stale by removing it
    target = tmp_path / config.config_dir / "settings.json"
    target.unlink()

    with (
        patch(
            "reins.cli.commands.update._find_reins_root",
            return_value=tmp_path,
        ),
        patch(
            "reins.cli.commands.update._resolve_platform_config",
            return_value=config,
        ),
    ):
        result = runner.invoke(app, ["update", "--dry-run"])
    assert result.exit_code == 0
    assert "missing" in result.output
    # File should still be missing (not regenerated)
    assert not target.exists()


def test_update_force_updates_without_prompt(tmp_path: Path) -> None:
    """Force flag regenerates files without prompting."""
    (tmp_path / ".reins").mkdir()
    config = get_platform(PlatformType.CLAUDE_CODE)
    assert config is not None
    engine = DescriptorEngine(tmp_path)
    engine.generate(config)

    # Make a file stale by removing it
    target = tmp_path / config.config_dir / "settings.json"
    target.unlink()
    assert not target.exists()

    with (
        patch(
            "reins.cli.commands.update._find_reins_root",
            return_value=tmp_path,
        ),
        patch(
            "reins.cli.commands.update._resolve_platform_config",
            return_value=config,
        ),
    ):
        result = runner.invoke(app, ["update", "--force"])
    assert result.exit_code == 0
    assert "Updated" in result.output
    assert target.exists()
