from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_spec_init_tracks_managed_templates(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['fastapi>=0.1']\n",
        encoding="utf-8",
    )
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.yaml").write_text("{}", encoding="utf-8")

    result = invoke(repo, monkeypatch, ["spec", "init", "--package", "auth"])

    assert result.exit_code == 0
    assert (repo / ".reins" / "spec" / "backend" / "index.md").exists()
    assert (repo / ".reins" / "spec" / "auth" / "backend" / "index.md").exists()
    hashes = json.loads((repo / ".reins" / ".template-hashes.json").read_text(encoding="utf-8"))
    assert ".reins/spec/backend/index.md" in hashes
    assert ".reins/spec/auth/backend/index.md" in hashes
    assert "Project type: backend" in result.output
    assert "Platform: codex" in result.output


def test_spec_update_keeps_customized_index_without_force(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    invoke(repo, monkeypatch, ["spec", "init"])

    backend_index = repo / ".reins" / "spec" / "backend" / "index.md"
    backend_index.write_text("# Customized Backend\n", encoding="utf-8")

    result = invoke(repo, monkeypatch, ["spec", "update"])

    assert result.exit_code == 0
    assert backend_index.read_text(encoding="utf-8") == "# Customized Backend\n"
    assert "No spec updates applied" in result.output


def test_spec_fetch_from_local_registry_updates_index(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    invoke(repo, monkeypatch, ["spec", "init"])

    remote_root = tmp_path / "remote-specs"
    (remote_root / "backend").mkdir(parents=True)
    (remote_root / "backend" / "query-patterns.md").write_text("# Query Patterns\n", encoding="utf-8")

    result = invoke(
        repo,
        monkeypatch,
        ["spec", "fetch", "backend", "--remote", str(remote_root)],
    )

    assert result.exit_code == 0
    layer_target = repo / ".reins" / "spec" / "backend" / "query-patterns.md"
    assert layer_target.exists()
    assert "query-patterns.md" in (repo / ".reins" / "spec" / "backend" / "index.md").read_text(encoding="utf-8")


def test_spec_validate_fix_restores_missing_checklist(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    spec_root = repo / ".reins" / "spec"
    (spec_root / "backend").mkdir(parents=True)
    (spec_root / "backend" / "index.md").write_text("# Backend\n", encoding="utf-8")
    (spec_root / "guides").mkdir(parents=True)
    (spec_root / "guides" / "index.md").write_text(
        "# Guides\n\n## Pre-Development Checklist\n\n- [ ] Read guide\n",
        encoding="utf-8",
    )

    result = invoke(repo, monkeypatch, ["spec", "validate", "--fix"])

    assert result.exit_code == 0
    fixed = (spec_root / "backend" / "index.md").read_text(encoding="utf-8")
    assert "Pre-Development Checklist" in fixed
