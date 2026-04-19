from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_events


def test_spec_cli_end_to_end(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['fastapi>=0.1']\n",
        encoding="utf-8",
    )

    init_result = invoke(repo, monkeypatch, ["spec", "init", "--package", "cli"])
    assert init_result.exit_code == 0

    remote_root = tmp_path / "registry"
    (remote_root / "guides").mkdir(parents=True)
    (remote_root / "guides" / "release-flow.md").write_text("# Release Flow\n", encoding="utf-8")
    fetch_result = invoke(
        repo,
        monkeypatch,
        ["spec", "fetch", "guides", "--remote", str(remote_root)],
    )
    assert fetch_result.exit_code == 0
    assert (repo / ".reins" / "spec" / "guides" / "release-flow.md").exists()

    update_root = tmp_path / "update-registry"
    (update_root / "backend").mkdir(parents=True)
    (update_root / "backend" / "index.md").write_text(
        "# Backend Specifications\n\n## Pre-Development Checklist\n\n- [ ] Updated backend checklist item\n",
        encoding="utf-8",
    )
    update_result = invoke(
        repo,
        monkeypatch,
        ["spec", "update", "--remote", str(update_root)],
    )
    assert update_result.exit_code == 0
    assert "Updated spec files" in update_result.output

    validate_result = invoke(repo, monkeypatch, ["spec", "validate"])
    assert validate_result.exit_code == 0

    event_types = [event.type for event in load_events(repo)]
    assert "spec.initialized" in event_types
    assert "spec.fetched" in event_types
    assert "spec.updated" in event_types
    assert "spec.validated" in event_types
