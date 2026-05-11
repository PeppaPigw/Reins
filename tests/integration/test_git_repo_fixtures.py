"""Integration tests for git repository fixtures.

Validates that git_repo, git_repo_with_history, and git_repo_with_conflicts
fixtures produce correct, usable git repositories for integration testing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# TestGitRepoFixture
# ---------------------------------------------------------------------------


class TestGitRepoFixture:
    """Tests for the basic git_repo fixture."""

    def test_git_repo_is_valid_repository(self, git_repo: Path):
        assert (git_repo / ".git").exists()
        result = _git(["status"], cwd=git_repo)
        assert result.returncode == 0

    def test_git_repo_has_initial_commit(self, git_repo: Path):
        result = _git(["log", "--oneline"], cwd=git_repo)
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) >= 1

    def test_git_repo_has_clean_working_tree(self, git_repo: Path):
        result = _git(["status", "--porcelain"], cwd=git_repo)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# TestGitRepoWithHistory
# ---------------------------------------------------------------------------


class TestGitRepoWithHistory:
    """Tests for the git_repo_with_history fixture."""

    def test_repo_has_multiple_commits(self, git_repo_with_history):
        repo_path, _ = git_repo_with_history
        result = _git(["log", "--oneline", "--all"], cwd=repo_path)
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().splitlines() if l]
        assert len(lines) >= 5

    def test_repo_has_branches(self, git_repo_with_history):
        repo_path, branch_names = git_repo_with_history
        result = _git(["branch", "--list"], cwd=repo_path)
        assert result.returncode == 0
        branches = result.stdout.strip()
        for name in branch_names:
            assert name in branches

    def test_branch_divergence(self, git_repo_with_history):
        repo_path, _ = git_repo_with_history
        # Commits in dev that are not in main
        result = _git(["log", "--oneline", "main..dev"], cwd=repo_path)
        assert result.returncode == 0
        diverged = [l for l in result.stdout.strip().splitlines() if l]
        assert len(diverged) >= 2

    def test_can_checkout_branches(self, git_repo_with_history):
        repo_path, _ = git_repo_with_history
        # Get current HEAD
        head_before = _git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()

        # Checkout dev
        result = _git(["checkout", "dev"], cwd=repo_path)
        assert result.returncode == 0
        head_dev = _git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()
        assert head_dev != head_before

        # Checkout main
        result = _git(["checkout", "main"], cwd=repo_path)
        assert result.returncode == 0
        head_main = _git(["rev-parse", "HEAD"], cwd=repo_path).stdout.strip()
        assert head_main == head_before


# ---------------------------------------------------------------------------
# TestGitRepoWithConflicts
# ---------------------------------------------------------------------------


class TestGitRepoWithConflicts:
    """Tests for the git_repo_with_conflicts fixture."""

    def test_merge_produces_conflict(self, git_repo_with_conflicts):
        repo_path, _ = git_repo_with_conflicts
        result = _git(["merge", "feature"], cwd=repo_path)
        # Merge should fail due to conflict
        assert result.returncode != 0

    def test_conflicting_file_identified(self, git_repo_with_conflicts):
        repo_path, conflicting_file = git_repo_with_conflicts
        # Attempt merge
        _git(["merge", "feature"], cwd=repo_path)
        # Check unmerged files
        result = _git(["diff", "--name-only", "--diff-filter=U"], cwd=repo_path)
        assert conflicting_file in result.stdout


# ---------------------------------------------------------------------------
# TestGitOperationsIntegration
# ---------------------------------------------------------------------------


class TestGitOperationsIntegration:
    """Tests for git operations using the fixtures."""

    def test_worktree_creation_in_fixture_repo(self, git_repo_with_history, tmp_path):
        repo_path, _ = git_repo_with_history
        worktree_dir = tmp_path / "worktree_test"
        result = _git(
            ["worktree", "add", str(worktree_dir), "dev"], cwd=repo_path
        )
        assert result.returncode == 0
        assert worktree_dir.exists()
        assert (worktree_dir / ".git").exists()
        # Clean up
        _git(["worktree", "remove", str(worktree_dir)], cwd=repo_path)

    def test_commit_and_push_in_fixture(self, git_repo: Path):
        # Create a new file, stage, commit
        new_file = git_repo / "new_feature.py"
        new_file.write_text("# New feature\n", encoding="utf-8")
        _git(["add", "new_feature.py"], cwd=git_repo)
        result = _git(["commit", "-m", "feat: add new feature"], cwd=git_repo)
        assert result.returncode == 0
        # Verify commit in log
        log = _git(["log", "--oneline"], cwd=git_repo)
        assert "add new feature" in log.stdout

    def test_tag_creation(self, git_repo: Path):
        result = _git(["tag", "v0.1.0"], cwd=git_repo)
        assert result.returncode == 0
        tags = _git(["tag", "-l"], cwd=git_repo)
        assert "v0.1.0" in tags.stdout

    def test_stash_operations(self, git_repo: Path):
        # Modify a tracked file
        readme = git_repo / "README.md"
        original = readme.read_text(encoding="utf-8")
        readme.write_text(original + "Modified line\n", encoding="utf-8")

        # Stash
        result = _git(["stash"], cwd=git_repo)
        assert result.returncode == 0

        # Working tree should be clean
        status = _git(["status", "--porcelain"], cwd=git_repo)
        # Filter out untracked files from other tests in session-scoped fixture
        tracked_changes = [
            l for l in status.stdout.strip().splitlines()
            if l and not l.startswith("??")
        ]
        assert tracked_changes == []

        # Pop stash
        result = _git(["stash", "pop"], cwd=git_repo)
        assert result.returncode == 0
        assert "Modified line" in readme.read_text(encoding="utf-8")
