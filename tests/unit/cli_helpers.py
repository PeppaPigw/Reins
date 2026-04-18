from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from reins.cli.main import app
from reins.cli import utils


def create_repo(tmp_path: Path, *, git: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".reins").mkdir()
    (repo / ".reins" / "tasks").mkdir()
    (repo / ".reins" / "spec").mkdir()
    (repo / ".reins" / "workspace").mkdir()
    if git:
        (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, check=True)
    return repo


def current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def runner() -> CliRunner:
    return CliRunner()


def invoke(repo: Path, monkeypatch, args: list[str]):
    monkeypatch.chdir(repo)
    return runner().invoke(app, args)


def load_events(repo: Path):
    return utils.load_all_events(repo)


def load_registry(repo: Path) -> dict:
    registry_path = repo / ".reins" / "registry.json"
    return json.loads(registry_path.read_text(encoding="utf-8"))
