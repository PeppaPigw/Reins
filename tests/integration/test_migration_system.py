from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reins.kernel.event.journal import EventJournal
from reins.migration.engine import MigrationEngine
from tests.integration.helpers import assert_event_types_in_order, load_run_events


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
                        "allowed_hashes": {"type": "array", "items": {"type": "string"}},
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
async def test_migration_system_integration(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_dir = tmp_path / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)

    (repo_root / "old-name.txt").write_text("rename me\n", encoding="utf-8")
    (repo_root / "delete-me.txt").write_text("template\n", encoding="utf-8")
    (repo_root / "keep-me.txt").write_text("changed content\n", encoding="utf-8")
    delete_hash = hashlib.sha256((repo_root / "delete-me.txt").read_bytes()).hexdigest()
    keep_hash = hashlib.sha256(b"original template\n").hexdigest()

    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "rename",
                "from_path": "old-name.txt",
                "to_path": "new-name.txt",
                "description": "Rename template file",
            }
        ],
    )
    _write_manifest(
        manifest_dir,
        "0.2.0",
        [
            {
                "type": "safe-file-delete",
                "from_path": "delete-me.txt",
                "allowed_hashes": [delete_hash],
                "description": "Delete unchanged template",
            },
            {
                "type": "safe-file-delete",
                "from_path": "keep-me.txt",
                "allowed_hashes": [keep_hash],
                "description": "Skip modified file",
            },
        ],
    )

    run_id = "migration-system"
    journal = EventJournal(tmp_path / "journal.jsonl")
    engine = MigrationEngine(
        repo_root=repo_root,
        journal=journal,
        run_id=run_id,
        manifest_dir=manifest_dir,
    )

    dry_run = await engine.migrate(from_version="0.0.0", to_version="0.2.0", dry_run=True)
    assert [result.status for result in dry_run] == ["dry_run", "dry_run", "skipped"]
    assert (repo_root / "old-name.txt").exists()
    assert (repo_root / "delete-me.txt").exists()

    applied = await engine.migrate(from_version="0.0.0", to_version="0.2.0")
    assert [result.status for result in applied] == ["applied", "applied", "skipped"]
    assert not (repo_root / "old-name.txt").exists()
    assert (repo_root / "new-name.txt").exists()
    assert not (repo_root / "delete-me.txt").exists()
    assert (repo_root / "keep-me.txt").exists()

    rerun = await engine.migrate(from_version="0.0.0", to_version="0.2.0")
    assert [result.status for result in rerun] == ["skipped", "skipped", "skipped"]

    events = await load_run_events(journal, run_id)
    assert_event_types_in_order(
        events,
        [
            "migration.started",
            "migration.operation",
            "migration.completed",
        ],
    )
    assert any(
        event.payload.get("reason") == "hash_mismatch"
        for event in events
        if event.type == "migration.operation"
    )


@pytest.mark.asyncio
async def test_migration_system_rolls_back_on_failure(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_dir = tmp_path / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)

    (repo_root / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (repo_root / "beta.txt").write_text("beta\n", encoding="utf-8")
    _write_manifest(
        manifest_dir,
        "0.1.0",
        [
            {
                "type": "rename",
                "from_path": "alpha.txt",
                "to_path": "gamma.txt",
                "description": "Rename alpha to gamma",
            },
            {
                "type": "rename",
                "from_path": "beta.txt",
                "to_path": "gamma.txt",
                "description": "Conflicting rename should fail",
            },
        ],
    )

    run_id = "migration-rollback"
    journal = EventJournal(tmp_path / "journal.jsonl")
    engine = MigrationEngine(
        repo_root=repo_root,
        journal=journal,
        run_id=run_id,
        manifest_dir=manifest_dir,
    )

    with pytest.raises(Exception):
        await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert (repo_root / "alpha.txt").exists()
    assert (repo_root / "beta.txt").exists()
    assert not (repo_root / "gamma.txt").exists()

    events = await load_run_events(journal, run_id)
    assert "migration.failed" in [event.type for event in events]
    assert any(
        event.type == "migration.operation" and event.payload["status"] == "rolled_back"
        for event in events
    )
