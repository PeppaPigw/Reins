"""Changelog generation from conventional commits."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?"
    r":\s*(?P<description>.+)$"
)


@dataclass(frozen=True)
class ConventionalCommit:
    """A parsed conventional commit."""

    hash: str
    type: str
    scope: str | None
    description: str
    body: str | None
    breaking: bool
    date: str


@dataclass
class ChangelogEntry:
    """A grouped changelog entry for a single version."""

    version: str
    date: str
    features: list[ConventionalCommit] = field(default_factory=list)
    fixes: list[ConventionalCommit] = field(default_factory=list)
    breaking_changes: list[ConventionalCommit] = field(default_factory=list)
    other: list[ConventionalCommit] = field(default_factory=list)


def parse_conventional_commit(
    message: str,
    hash: str = "",
    date: str = "",
) -> ConventionalCommit | None:
    """Parse a commit message in conventional commit format.

    Returns None if the message does not match the expected format.
    """
    lines = message.strip().splitlines()
    if not lines:
        return None

    first_line = lines[0].strip()
    match = _CONVENTIONAL_RE.match(first_line)
    if not match:
        return None

    body = "\n".join(lines[1:]).strip() or None
    breaking = bool(match.group("breaking"))

    # Also detect BREAKING CHANGE in body
    if body and "BREAKING CHANGE:" in body:
        breaking = True

    return ConventionalCommit(
        hash=hash,
        type=match.group("type"),
        scope=match.group("scope"),
        description=match.group("description"),
        body=body,
        breaking=breaking,
        date=date,
    )


class ChangelogGenerator:
    """Generates changelogs from git conventional commits."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def parse_commits(self, since_tag: str | None = None) -> list[ConventionalCommit]:
        """Parse git log into conventional commits.

        If since_tag is provided, only includes commits after that tag.
        """
        cmd = ["git", "log", "--format=%H%n%aI%n%B%n---END---"]
        if since_tag:
            cmd.append(f"{since_tag}..HEAD")

        result = subprocess.run(
            cmd,
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []

        commits: list[ConventionalCommit] = []
        raw_entries = result.stdout.split("---END---\n")

        for entry in raw_entries:
            entry = entry.strip()
            if not entry:
                continue
            lines = entry.splitlines()
            if len(lines) < 3:
                continue
            commit_hash = lines[0].strip()
            commit_date = lines[1].strip()[:10]  # YYYY-MM-DD
            message = "\n".join(lines[2:]).strip()

            parsed = parse_conventional_commit(message, hash=commit_hash, date=commit_date)
            if parsed is not None:
                commits.append(parsed)

        return commits

    def generate_entry(
        self, version: str, commits: list[ConventionalCommit]
    ) -> ChangelogEntry:
        """Group commits into a changelog entry by type."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = ChangelogEntry(version=version, date=today)

        for commit in commits:
            if commit.breaking:
                entry.breaking_changes.append(commit)
            elif commit.type == "feat":
                entry.features.append(commit)
            elif commit.type == "fix":
                entry.fixes.append(commit)
            else:
                entry.other.append(commit)

        return entry

    def render_markdown(self, entry: ChangelogEntry) -> str:
        """Render a changelog entry as markdown."""
        lines: list[str] = [f"## [{entry.version}] - {entry.date}", ""]

        if entry.breaking_changes:
            lines.append("### Breaking Changes")
            lines.append("")
            for commit in entry.breaking_changes:
                lines.append(self._format_commit(commit))
            lines.append("")

        if entry.features:
            lines.append("### Features")
            lines.append("")
            for commit in entry.features:
                lines.append(self._format_commit(commit))
            lines.append("")

        if entry.fixes:
            lines.append("### Bug Fixes")
            lines.append("")
            for commit in entry.fixes:
                lines.append(self._format_commit(commit))
            lines.append("")

        if entry.other:
            lines.append("### Other Changes")
            lines.append("")
            for commit in entry.other:
                lines.append(self._format_commit(commit))
            lines.append("")

        return "\n".join(lines)

    def update_changelog_file(
        self, entry: ChangelogEntry, changelog_path: Path | None = None
    ) -> None:
        """Prepend a new entry to CHANGELOG.md (creates if not exists)."""
        path = changelog_path or (self._repo_root / "CHANGELOG.md")
        new_content = self.render_markdown(entry)

        if path.exists():
            existing = path.read_text(encoding="utf-8")
            # Insert after the title line if present
            if existing.startswith("# "):
                title_end = existing.index("\n") + 1
                combined = existing[:title_end] + "\n" + new_content + "\n" + existing[title_end:]
            else:
                combined = new_content + "\n" + existing
        else:
            combined = "# Changelog\n\n" + new_content

        path.write_text(combined, encoding="utf-8")

    @staticmethod
    def _format_commit(commit: ConventionalCommit) -> str:
        """Format a single commit as a markdown list item."""
        short_hash = commit.hash[:7] if commit.hash else ""
        if commit.scope:
            prefix = f"- **{commit.scope}:** {commit.description}"
        else:
            prefix = f"- {commit.description}"
        if short_hash:
            return f"{prefix} ({short_hash})"
        return prefix
