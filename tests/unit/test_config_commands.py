from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_config_init_creates_templates(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    result = invoke(repo, monkeypatch, ["config", "init"])

    assert result.exit_code == 0
    assert (repo / ".reins" / "config.yaml").exists()
    assert (repo / ".reins" / "worktree.yaml").exists()


def test_config_get_set_and_show(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / "packages" / "cli").mkdir(parents=True)
    invoke(repo, monkeypatch, ["config", "init"])

    assert invoke(repo, monkeypatch, ["config", "set", "max_journal_lines", "3000"]).exit_code == 0
    assert invoke(repo, monkeypatch, ["config", "set", "packages.cli.path", "packages/cli"]).exit_code == 0
    assert invoke(repo, monkeypatch, ["config", "set", "default_package", "cli"]).exit_code == 0

    get_lines = invoke(repo, monkeypatch, ["config", "get", "max_journal_lines"])
    assert get_lines.exit_code == 0
    assert get_lines.output.strip() == "3000"

    get_package = invoke(repo, monkeypatch, ["config", "get", "packages.cli.path"])
    assert get_package.exit_code == 0
    assert get_package.output.strip() == "packages/cli"

    show = invoke(repo, monkeypatch, ["config", "show"])
    assert show.exit_code == 0
    assert "default_package: cli" in show.output
