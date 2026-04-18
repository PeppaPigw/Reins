from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reins.kernel.event.journal import EventJournal
from reins.migration.engine import MigrationEngine


def _write_schema(manifest_dir: Path) -> None:
    schema = {
        "type": "object",
        "required": ["version", "migrations"],
        "properties": {
            "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
            "migrations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["type", "description"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["rename", "delete", "safe-file-delete", "rename-dir"],
                        },
                        "from_path": {"type": ["string", "null"]},
                        "to_path": {"type": ["string", "null"]},
                        "allowed_hashes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "description": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }
    (manifest_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")


def _write_manifest(manifest_dir: Path, version: str, migrations: list[dict[str, object]]) -> None:
    (manifest_dir / f"{version}.json").write_text(
        json.dumps({"version": version, "migrations": migrations}, indent=2),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_rename_operation_applies_once(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "rename",
                "from_path": "old.txt",
                "to_path": "new.txt",
                "description": "Rename old.txt to new.txt",
            }
        ],
    )
    (repo_root / "old.txt").write_text("hello\n", encoding="utf-8")

    engine = MigrationEngine(
        repo_root=repo_root,
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        manifest_dir=manifest_dir,
    )

    results = await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert results[0].status == "applied"
    assert not (repo_root / "old.txt").exists()
    assert (repo_root / "new.txt").read_text(encoding="utf-8") == "hello\n"

    second = await engine.migrate(from_version="0.0.0", to_version="0.1.0")
    assert second[0].status == "skipped"


@pytest.mark.asyncio
async def test_delete_operation_handles_missing_file_gracefully(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "delete",
                "from_path": "obsolete.txt",
                "description": "Delete obsolete file",
            }
        ],
    )

    engine = MigrationEngine(
        repo_root=repo_root,
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        manifest_dir=manifest_dir,
    )

    results = await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert results[0].status == "skipped"
    assert results[0].reason == "missing_source"


@pytest.mark.asyncio
async def test_safe_file_delete_respects_allowed_hashes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    template_path = repo_root / "template.txt"
    template_path.write_text("known-template\n", encoding="utf-8")
    allowed_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "safe-file-delete",
                "from_path": "template.txt",
                "allowed_hashes": [allowed_hash],
                "description": "Delete unchanged template file",
            }
        ],
    )

    engine = MigrationEngine(
        repo_root=repo_root,
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        manifest_dir=manifest_dir,
    )

    results = await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert results[0].status == "applied"
    assert not template_path.exists()


@pytest.mark.asyncio
async def test_rename_dir_operation_and_dry_run(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "rename-dir",
                "from_path": "old-dir",
                "to_path": "new-dir",
                "description": "Rename directory",
            }
        ],
    )
    (repo_root / "old-dir").mkdir()
    (repo_root / "old-dir" / "file.txt").write_text("content\n", encoding="utf-8")

    engine = MigrationEngine(
        repo_root=repo_root,
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        manifest_dir=manifest_dir,
    )

    dry_run = await engine.migrate(
        from_version="0.0.0",
        to_version="0.1.0",
        dry_run=True,
    )

    assert dry_run[0].status == "dry_run"
    assert (repo_root / "old-dir").exists()
    assert not (repo_root / "new-dir").exists()
