from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_main_help_includes_overview_and_common_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    result = invoke(repo, monkeypatch, ["--help"])

    assert result.exit_code == 0
    assert "Reins - Multi-Agent Orchestration System" in result.output
    assert "Key Features" in result.output
    assert "completion zsh" in result.output


def test_completion_command_outputs_shell_script(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    result = invoke(repo, monkeypatch, ["completion", "zsh"])

    assert result.exit_code == 0
    assert "_REINS_COMPLETE" in result.output


def test_spec_help_includes_new_examples(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    result = invoke(repo, monkeypatch, ["spec", "init", "--help"])

    assert result.exit_code == 0
    assert "--platform" in result.output
    assert "--type" in result.output
    assert "reins spec init --type fullstack" in result.output


def test_worktree_help_includes_new_task_option(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    result = invoke(repo, monkeypatch, ["worktree", "create", "--help"])

    assert result.exit_code == 0
    assert "--task" in result.output
    assert "feature-lane --task" in result.output
