"""Integration tests for the `reins init` command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from reins.cli.main import app
from reins.cli import utils


def _invoke(repo_root: Path, monkeypatch, args: list[str], *, input_text: str | None = None):
    monkeypatch.chdir(repo_root)
    return CliRunner().invoke(app, args, input=input_text)


def test_init_with_platform_flag_creates_reins_layout(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )

    result = _invoke(
        repo_root,
        monkeypatch,
        ["init", "--platform", "codex", "--project-type", "backend", "--developer", "peppa"],
    )

    assert result.exit_code == 0
    assert (repo_root / ".reins" / "spec" / "backend").exists()
    assert (repo_root / ".reins" / "spec" / "frontend").exists()
    assert (repo_root / ".reins" / "journal.jsonl").exists()
    assert (repo_root / ".reins" / ".current-task").exists()
    assert (repo_root / ".codex" / "config.yaml").exists()
    assert (repo_root / ".codex" / "mcp.json").exists()

    events = utils.load_all_events(repo_root)
    assert any(event.type == "project.initialized" for event in events)


def test_init_interactive_platform_selection(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0"}}),
        encoding="utf-8",
    )

    result = _invoke(
        repo_root,
        monkeypatch,
        ["init", "--project-type", "frontend"],
        input_text="cursor\n",
    )

    assert result.exit_code == 0
    assert (repo_root / ".cursorrules").exists()
    assert (repo_root / ".cursor" / "settings.json").exists()
    assert "Project type: frontend" in result.output


def test_init_auto_detects_platform_and_project_type(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".claude").mkdir()
    (repo_root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['fastapi>=0.1']\n",
        encoding="utf-8",
    )
    (repo_root / "package.json").write_text(
        json.dumps({"dependencies": {"next": "^15.0.0"}}),
        encoding="utf-8",
    )

    result = _invoke(repo_root, monkeypatch, ["init"])

    assert result.exit_code == 0
    assert (repo_root / ".claude" / "hooks" / "session-start.py").exists()
    assert "Claude Code" in result.output
    assert "fullstack" in result.output


def test_init_invalid_platform_emits_cli_error(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = _invoke(repo_root, monkeypatch, ["init", "--platform", "not-real"])

    assert result.exit_code == 1
    events = utils.load_all_events(repo_root)
    assert any(event.type == "cli.error" for event in events)
