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
async def test_full_migration_flow_is_idempotent(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)

    (repo_root / "old-name.txt").write_text("rename me\n", encoding="utf-8")
    (repo_root / "delete-me.txt").write_text("template\n", encoding="utf-8")
    allowed_hash = hashlib.sha256((repo_root / "delete-me.txt").read_bytes()).hexdigest()

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

    first = await engine.migrate(from_version="0.0.0", to_version="0.2.0")
    second = await engine.migrate(from_version="0.0.0", to_version="0.2.0")

    assert [result.status for result in first] == ["applied", "applied"]
    assert [result.status for result in second] == ["skipped", "skipped"]
    assert not (repo_root / "old-name.txt").exists()
    assert (repo_root / "new-name.txt").exists()
    assert not (repo_root / "delete-me.txt").exists()


@pytest.mark.asyncio
async def test_migration_rollback_restores_previous_changes_on_failure(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    manifest_dir = tmp_path / "migrations" / "manifests"
    repo_root.mkdir()
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

    engine = MigrationEngine(
        repo_root=repo_root,
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        manifest_dir=manifest_dir,
    )

    with pytest.raises(Exception):
        await engine.migrate(from_version="0.0.0", to_version="0.1.0")

    assert (repo_root / "alpha.txt").exists()
    assert (repo_root / "beta.txt").exists()
    assert not (repo_root / "gamma.txt").exists()
