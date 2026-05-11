"""Tests for changelog generation module."""

from __future__ import annotations

import subprocess
from pathlib import Path

from reins.packaging.changelog import (
    ChangelogEntry,
    ChangelogGenerator,
    ConventionalCommit,
    parse_conventional_commit,
)


def test_parse_conventional_commit_feat():
    commit = parse_conventional_commit("feat: add user authentication")
    assert commit is not None
    assert commit.type == "feat"
    assert commit.scope is None
    assert commit.description == "add user authentication"
    assert commit.breaking is False


def test_parse_conventional_commit_fix_with_scope():
    commit = parse_conventional_commit("fix(api): handle null response body")
    assert commit is not None
    assert commit.type == "fix"
    assert commit.scope == "api"
    assert commit.description == "handle null response body"


def test_parse_conventional_commit_breaking():
    commit = parse_conventional_commit("feat!: remove deprecated endpoints")
    assert commit is not None
    assert commit.breaking is True

    # Also via body
    msg = "feat: change API\n\nBREAKING CHANGE: removed v1 endpoints"
    commit2 = parse_conventional_commit(msg)
    assert commit2 is not None
    assert commit2.breaking is True


def test_parse_conventional_commit_invalid_returns_none():
    assert parse_conventional_commit("just a regular message") is None
    assert parse_conventional_commit("") is None
    assert parse_conventional_commit("Merge branch 'main'") is None


def test_generate_entry_groups_by_type():
    commits = [
        ConventionalCommit(
            hash="aaa", type="feat", scope=None,
            description="new feature", body=None, breaking=False, date="2024-01-01",
        ),
        ConventionalCommit(
            hash="bbb", type="fix", scope="core",
            description="fix bug", body=None, breaking=False, date="2024-01-02",
        ),
        ConventionalCommit(
            hash="ccc", type="feat", scope=None,
            description="breaking thing", body=None, breaking=True, date="2024-01-03",
        ),
        ConventionalCommit(
            hash="ddd", type="docs", scope=None,
            description="update readme", body=None, breaking=False, date="2024-01-04",
        ),
    ]
    gen = ChangelogGenerator(Path("."))
    entry = gen.generate_entry("1.0.0", commits)
    assert len(entry.features) == 1
    assert len(entry.fixes) == 1
    assert len(entry.breaking_changes) == 1
    assert len(entry.other) == 1


def test_render_markdown_has_sections():
    commits = [
        ConventionalCommit(
            hash="abc1234", type="feat", scope="auth",
            description="add login", body=None, breaking=False, date="2024-01-01",
        ),
        ConventionalCommit(
            hash="def5678", type="fix", scope=None,
            description="fix crash", body=None, breaking=False, date="2024-01-02",
        ),
    ]
    gen = ChangelogGenerator(Path("."))
    entry = gen.generate_entry("1.1.0", commits)
    md = gen.render_markdown(entry)
    assert "## [1.1.0]" in md
    assert "### Features" in md
    assert "### Bug Fixes" in md
    assert "**auth:** add login (abc1234)" in md
    assert "fix crash (def5678)" in md


def test_render_markdown_includes_breaking_changes():
    commits = [
        ConventionalCommit(
            hash="fff0000", type="feat", scope="api",
            description="remove v1", body=None, breaking=True, date="2024-01-01",
        ),
    ]
    gen = ChangelogGenerator(Path("."))
    entry = gen.generate_entry("2.0.0", commits)
    md = gen.render_markdown(entry)
    assert "### Breaking Changes" in md
    assert "**api:** remove v1" in md


def test_render_markdown_skips_empty_sections():
    commits = [
        ConventionalCommit(
            hash="aaa", type="feat", scope=None,
            description="only feature", body=None, breaking=False, date="2024-01-01",
        ),
    ]
    gen = ChangelogGenerator(Path("."))
    entry = gen.generate_entry("1.0.0", commits)
    md = gen.render_markdown(entry)
    assert "### Features" in md
    assert "### Bug Fixes" not in md
    assert "### Breaking Changes" not in md
    assert "### Other Changes" not in md


def test_changelog_generator_parse_commits(tmp_path: Path):
    """Test parsing commits from a real git repo."""
    # Set up a temporary git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    # Create commits
    (tmp_path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat(core): initial feature"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "file.txt").write_text("world")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: resolve startup crash"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    gen = ChangelogGenerator(tmp_path)
    commits = gen.parse_commits()
    assert len(commits) == 2
    assert commits[0].type == "fix"  # Most recent first
    assert commits[1].type == "feat"


def test_update_changelog_file_creates_new(tmp_path: Path):
    gen = ChangelogGenerator(tmp_path)
    entry = ChangelogEntry(
        version="1.0.0",
        date="2024-01-15",
        features=[
            ConventionalCommit(
                hash="abc", type="feat", scope=None,
                description="first release", body=None, breaking=False, date="2024-01-15",
            ),
        ],
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    gen.update_changelog_file(entry, changelog_path)
    content = changelog_path.read_text()
    assert "# Changelog" in content
    assert "## [1.0.0] - 2024-01-15" in content
    assert "first release" in content


def test_update_changelog_file_prepends(tmp_path: Path):
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text("# Changelog\n\n## [0.1.0] - 2024-01-01\n\n- Initial\n")

    gen = ChangelogGenerator(tmp_path)
    entry = ChangelogEntry(
        version="0.2.0",
        date="2024-02-01",
        features=[
            ConventionalCommit(
                hash="def", type="feat", scope=None,
                description="new stuff", body=None, breaking=False, date="2024-02-01",
            ),
        ],
    )
    gen.update_changelog_file(entry, changelog_path)
    content = changelog_path.read_text()
    # New entry should come before old entry
    idx_new = content.index("[0.2.0]")
    idx_old = content.index("[0.1.0]")
    assert idx_new < idx_old
