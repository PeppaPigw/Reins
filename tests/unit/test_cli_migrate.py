from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


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
                        "type": {"type": "string"},
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


def test_migrate_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    manifest_dir = repo / "migrations" / "manifests"
    manifest_dir.mkdir(parents=True)
    _write_schema(manifest_dir)

    create_result = invoke(repo, monkeypatch, ["migrate", "create", "0.2.0"])
    assert create_result.exit_code == 0
    assert (manifest_dir / "0.2.0.json").exists()

    validate = invoke(repo, monkeypatch, ["migrate", "validate", str(manifest_dir / "0.2.0.json")])
    assert validate.exit_code == 0

    old_file = repo / "old.txt"
    old_file.write_text("hello\n", encoding="utf-8")
    (manifest_dir / "0.1.0.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "migrations": [
                    {
                        "type": "rename",
                        "from_path": "old.txt",
                        "to_path": "new.txt",
                        "description": "Rename old file",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    list_result = invoke(repo, monkeypatch, ["migrate", "list"])
    assert list_result.exit_code == 0
    assert "0.1.0" in list_result.output

    dry_run = invoke(repo, monkeypatch, ["migrate", "run", "--from", "0.0.0", "--to", "0.1.0", "--dry-run"])
    assert dry_run.exit_code == 0
    assert old_file.exists()

    run_result = invoke(repo, monkeypatch, ["migrate", "run", "--from", "0.0.0", "--to", "0.1.0"])
    assert run_result.exit_code == 0
    assert not old_file.exists()
    assert (repo / "new.txt").exists()
