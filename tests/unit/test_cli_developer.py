from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_events


def test_developer_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    init_result = invoke(repo, monkeypatch, ["developer", "init", "peppa"])
    assert init_result.exit_code == 0
    assert (repo / ".reins" / ".developer").exists()
    assert (repo / ".reins" / "workspace" / "peppa" / "journal-1.md").exists()
    assert (repo / ".reins" / "workspace" / "peppa" / "index.md").exists()

    show_result = invoke(repo, monkeypatch, ["developer", "show"])
    assert show_result.exit_code == 0
    assert "peppa" in show_result.output

    workspace_info = invoke(repo, monkeypatch, ["developer", "workspace-info"])
    assert workspace_info.exit_code == 0
    assert "journal_files" in workspace_info.output

    assert "developer.initialized" in [event.type for event in load_events(repo)]
