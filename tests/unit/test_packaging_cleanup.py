"""Tests for packaging manifest and cleanup logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from reins.packaging.cleanup import CleanupEngine, CleanupResult
from reins.packaging.manifest import InstallManifest, ManifestEntry


def _setup_manifest(tmp_path: Path) -> InstallManifest:
    """Create a manifest rooted at tmp_path."""
    (tmp_path / ".reins").mkdir(parents=True, exist_ok=True)
    return InstallManifest(tmp_path)


def test_manifest_record_file(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    test_file = tmp_path / "config.yaml"
    test_file.write_text("key: value\n")

    manifest.record_file(test_file, created_by="init")

    entries = manifest.get_files()
    assert len(entries) == 1
    assert entries[0].path == "config.yaml"
    assert entries[0].entry_type == "file"
    assert entries[0].created_by == "init"
    assert entries[0].checksum is not None


def test_manifest_record_directory(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    test_dir = tmp_path / "hooks"
    test_dir.mkdir()

    manifest.record_directory(test_dir, created_by="platform")

    entries = manifest.get_directories()
    assert len(entries) == 1
    assert entries[0].path == "hooks"
    assert entries[0].entry_type == "directory"
    assert entries[0].created_by == "platform"
    assert entries[0].checksum is None


def test_manifest_save_and_load(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    test_file = tmp_path / "a.txt"
    test_file.write_text("hello")
    manifest.record_file(test_file, created_by="init")
    manifest.save()

    loaded = InstallManifest(tmp_path)
    loaded.load()
    entries = loaded.get_files()
    assert len(entries) == 1
    assert entries[0].path == "a.txt"
    assert entries[0].checksum is not None


def test_manifest_is_tracked(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("data")
    untracked = tmp_path / "untracked.txt"
    untracked.write_text("other")

    manifest.record_file(tracked, created_by="init")

    assert manifest.is_tracked(tracked) is True
    assert manifest.is_tracked(untracked) is False


def test_manifest_is_modified_detects_change(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    test_file = tmp_path / "config.yaml"
    test_file.write_text("original content")
    manifest.record_file(test_file, created_by="init")

    entry = manifest.get_files()[0]
    assert manifest.is_modified(entry) is False

    # Modify the file
    test_file.write_text("modified content")
    assert manifest.is_modified(entry) is True


def test_manifest_get_directories_deepest_first(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    shallow = tmp_path / "a"
    shallow.mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir()
    deepest = tmp_path / "a" / "b" / "c"
    deepest.mkdir()

    manifest.record_directory(shallow, created_by="init")
    manifest.record_directory(deep, created_by="init")
    manifest.record_directory(deepest, created_by="init")

    dirs = manifest.get_directories()
    assert dirs[0].path == "a/b/c"
    assert dirs[1].path == "a/b"
    assert dirs[2].path == "a"


def test_cleanup_plan_lists_files(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    f1 = tmp_path / "file1.txt"
    f1.write_text("content1")
    manifest.record_file(f1, created_by="init")

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.plan_cleanup()

    assert "file1.txt" in result.removed_files
    # File should still exist (dry-run)
    assert f1.exists()


def test_cleanup_plan_skips_modified_without_force(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    f1 = tmp_path / "config.yaml"
    f1.write_text("original")
    manifest.record_file(f1, created_by="init")

    # Modify the file after recording
    f1.write_text("user modified this")

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.plan_cleanup(force=False)

    assert "config.yaml" in result.skipped_modified
    assert "config.yaml" not in result.removed_files


def test_cleanup_plan_includes_modified_with_force(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    f1 = tmp_path / "config.yaml"
    f1.write_text("original")
    manifest.record_file(f1, created_by="init")

    f1.write_text("user modified this")

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.plan_cleanup(force=True)

    assert "config.yaml" in result.removed_files
    assert "config.yaml" not in result.skipped_modified


def test_cleanup_execute_removes_files(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    f1 = tmp_path / "generated.txt"
    f1.write_text("auto-generated")
    manifest.record_file(f1, created_by="init")
    manifest.save()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup()

    assert "generated.txt" in result.removed_files
    assert not f1.exists()


def test_cleanup_execute_removes_empty_dirs(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    d = tmp_path / "hooks"
    d.mkdir()
    f = d / "pre-commit"
    f.write_text("#!/bin/sh")
    manifest.record_directory(d, created_by="platform")
    manifest.record_file(f, created_by="platform")
    manifest.save()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup()

    assert "hooks/pre-commit" in result.removed_files
    assert "hooks" in result.removed_dirs
    assert not d.exists()


def test_cleanup_skips_missing_files(tmp_path: Path) -> None:
    manifest = _setup_manifest(tmp_path)
    f = tmp_path / "gone.txt"
    f.write_text("temp")
    manifest.record_file(f, created_by="init")
    # Remove before cleanup
    f.unlink()

    engine = CleanupEngine(tmp_path, manifest)
    result = engine.execute_cleanup()

    assert "gone.txt" in result.skipped_missing
