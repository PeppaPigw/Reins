"""Tests for the reins uninstall CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reins.packaging.cleanup import CleanupEngine
from reins.packaging.manifest import InstallManifest


def _create_manifest(tmp_path: Path, files: list[str]) -> None:
    """Helper to create a manifest with tracked files."""
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir(parents=True, exist_ok=True)
    manifest = InstallManifest(tmp_path)
    for f in files:
        fp = tmp_path / f
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f"generated: {f}")
        manifest.record_file(fp, created_by="init")
    manifest.save()


def test_uninstall_dry_run_shows_files(tmp_path: Path) -> None:
    _create_manifest(tmp_path, ["config.yaml", "hooks/pre-commit"])
    manifest = InstallManifest(tmp_path)
    manifest.load()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.plan_cleanup()

    assert "config.yaml" in result.removed_files
    assert "hooks/pre-commit" in result.removed_files
    # Files still exist after plan (dry-run equivalent)
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "hooks/pre-commit").exists()


def test_uninstall_removes_tracked_files(tmp_path: Path) -> None:
    _create_manifest(tmp_path, ["a.txt", "b.txt"])
    manifest = InstallManifest(tmp_path)
    manifest.load()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup()

    assert "a.txt" in result.removed_files
    assert "b.txt" in result.removed_files
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


def test_uninstall_skips_modified_without_force(tmp_path: Path) -> None:
    _create_manifest(tmp_path, ["config.yaml"])
    # Modify the file after manifest was created
    (tmp_path / "config.yaml").write_text("user edited this")

    manifest = InstallManifest(tmp_path)
    manifest.load()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup(force=False)

    assert "config.yaml" in result.skipped_modified
    assert (tmp_path / "config.yaml").exists()


def test_uninstall_removes_modified_with_force(tmp_path: Path) -> None:
    _create_manifest(tmp_path, ["config.yaml"])
    (tmp_path / "config.yaml").write_text("user edited this")

    manifest = InstallManifest(tmp_path)
    manifest.load()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup(force=True)

    assert "config.yaml" in result.removed_files
    assert not (tmp_path / "config.yaml").exists()


def test_uninstall_nothing_when_no_manifest(tmp_path: Path) -> None:
    manifest = InstallManifest(tmp_path)
    manifest.load()

    assert manifest.get_entries() == []


def test_uninstall_removes_empty_directories(tmp_path: Path) -> None:
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir(parents=True, exist_ok=True)
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    hook_file = hooks_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh")

    manifest = InstallManifest(tmp_path)
    manifest.record_directory(hooks_dir, created_by="platform")
    manifest.record_file(hook_file, created_by="platform")
    manifest.save()

    # Reload and execute
    manifest2 = InstallManifest(tmp_path)
    manifest2.load()
    engine = CleanupEngine(tmp_path, manifest2)
    result = engine.execute_cleanup()

    assert "hooks/pre-commit" in result.removed_files
    assert "hooks" in result.removed_dirs
    assert not hooks_dir.exists()


def test_uninstall_command_registered_in_app() -> None:
    from reins.cli.main import app

    command_names = [cmd.name for cmd in app.registered_commands]
    assert "uninstall" in command_names
