from __future__ import annotations

import json
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def _latest_task_json(repo: Path) -> dict[str, object]:
    task_dirs = sorted(path for path in (repo / ".reins" / "tasks").iterdir() if path.is_dir())
    assert task_dirs
    return json.loads((task_dirs[-1] / "task.json").read_text(encoding="utf-8"))


def test_default_package_flows_into_spec_and_task_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / "packages" / "cli").mkdir(parents=True)
    (repo / ".reins" / "config.yaml").write_text(
        """
packages:
  cli:
    path: packages/cli
default_package: cli
""".strip(),
        encoding="utf-8",
    )

    spec_init = invoke(repo, monkeypatch, ["spec", "init"])
    assert spec_init.exit_code == 0
    assert (repo / ".reins" / "spec" / "cli" / "index.md").exists()

    task_create = invoke(
        repo,
        monkeypatch,
        ["task", "create", "Config default package task", "--type", "backend"],
    )
    assert task_create.exit_code == 0
    assert _latest_task_json(repo)["metadata"]["package"] == "cli"

    validate = invoke(repo, monkeypatch, ["config", "validate"])
    assert validate.exit_code == 0
    assert "Configuration is valid." in validate.output


def test_config_validate_reports_invalid_project_and_worktree_config(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / ".reins" / "config.yaml").write_text(
        """
max_journal_lines: 20
packages:
  cli:
    path: packages/missing
default_package: docs
""".strip(),
        encoding="utf-8",
    )
    (repo / ".reins" / "worktree.yaml").write_text(
        """
copy: invalid
""".strip(),
        encoding="utf-8",
    )

    result = invoke(repo, monkeypatch, ["config", "validate"])

    assert result.exit_code == 1
    assert "max_journal_lines must be >= 100" in result.output
    assert "default_package 'docs' not in packages" in result.output
    assert "copy must be a list of strings" in result.output
