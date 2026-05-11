from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.integration.helpers import (
    EventJournal,
    build_orchestrator_bundle,
    make_harness,
)


@pytest.fixture
def integration_harness(tmp_path, monkeypatch):
    return make_harness(tmp_path, monkeypatch, git=True)


@pytest.fixture
def repo_root(integration_harness):
    return integration_harness.repo_root


@pytest.fixture
def journal(tmp_path):
    return EventJournal(tmp_path / "journal.jsonl")


@pytest.fixture
def orchestrator_bundle(tmp_path, repo_root):
    return build_orchestrator_bundle(tmp_path, repo_root=repo_root)


# ---------------------------------------------------------------------------
# Git repository fixtures (Plan 09-03)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture(scope="session")
def git_repo():
    """Session-scoped fixture providing a clean git repository with one commit."""
    with tempfile.TemporaryDirectory(prefix="reins_git_") as tmpdir:
        repo_path = Path(tmpdir)
        _run_git(["init", "-b", "main"], cwd=repo_path)
        _run_git(["config", "user.name", "Test User"], cwd=repo_path)
        _run_git(["config", "user.email", "test@reins.local"], cwd=repo_path)
        (repo_path / "README.md").write_text("# Test Repository\n", encoding="utf-8")
        _run_git(["add", "."], cwd=repo_path)
        _run_git(["commit", "-m", "Initial commit"], cwd=repo_path)
        yield repo_path


@pytest.fixture
def git_repo_with_history(tmp_path):
    """Function-scoped fixture providing a repo with 5 commits across 2 branches.

    main branch: 3 commits (init, feature-a, feature-b)
    dev branch: 2 additional commits
    Yields (repo_path, branch_names).
    """
    repo_path = tmp_path / "history_repo"
    repo_path.mkdir()
    _run_git(["init", "-b", "main"], cwd=repo_path)
    _run_git(["config", "user.name", "Test User"], cwd=repo_path)
    _run_git(["config", "user.email", "test@reins.local"], cwd=repo_path)

    # Commit 1: init
    (repo_path / "README.md").write_text("# Project\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "init: project setup"], cwd=repo_path)

    # Commit 2: feature-a
    (repo_path / "feature_a.py").write_text("# Feature A\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "feat: add feature-a"], cwd=repo_path)

    # Commit 3: feature-b
    (repo_path / "feature_b.py").write_text("# Feature B\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "feat: add feature-b"], cwd=repo_path)

    # Create dev branch and add 2 commits
    _run_git(["checkout", "-b", "dev"], cwd=repo_path)

    (repo_path / "dev_work.py").write_text("# Dev work 1\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "dev: work item 1"], cwd=repo_path)

    (repo_path / "dev_work_2.py").write_text("# Dev work 2\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "dev: work item 2"], cwd=repo_path)

    # Switch back to main
    _run_git(["checkout", "main"], cwd=repo_path)

    yield repo_path, ["main", "dev"]


@pytest.fixture
def git_repo_with_conflicts(tmp_path):
    """Function-scoped fixture providing a repo where main and feature modify the same file.

    Yields (repo_path, conflicting_file_name).
    """
    repo_path = tmp_path / "conflict_repo"
    repo_path.mkdir()
    _run_git(["init", "-b", "main"], cwd=repo_path)
    _run_git(["config", "user.name", "Test User"], cwd=repo_path)
    _run_git(["config", "user.email", "test@reins.local"], cwd=repo_path)

    # Initial commit with shared file
    conflict_file = "shared.txt"
    (repo_path / conflict_file).write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "init: add shared file"], cwd=repo_path)

    # Create feature branch and modify the file
    _run_git(["checkout", "-b", "feature"], cwd=repo_path)
    (repo_path / conflict_file).write_text(
        "line 1\nfeature change\nline 3\n", encoding="utf-8"
    )
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "feat: modify shared file"], cwd=repo_path)

    # Back to main and make a conflicting change
    _run_git(["checkout", "main"], cwd=repo_path)
    (repo_path / conflict_file).write_text(
        "line 1\nmain change\nline 3\n", encoding="utf-8"
    )
    _run_git(["add", "."], cwd=repo_path)
    _run_git(["commit", "-m", "fix: modify shared file on main"], cwd=repo_path)

    yield repo_path, conflict_file
