"""Semver version management for the Reins package."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class BumpType(str, Enum):
    """Type of version bump to apply."""

    major = "major"
    minor = "minor"
    patch = "patch"


_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z\-]+(?:\.[0-9A-Za-z\-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z\-]+(?:\.[0-9A-Za-z\-]+)*))?$"
)


@dataclass(frozen=True)
class VersionInfo:
    """Rich semantic version with prerelease and build metadata support."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build_metadata: str | None = None

    @classmethod
    def parse(cls, version_str: str) -> VersionInfo:
        """Parse a semver string into VersionInfo."""
        cleaned = version_str.strip().lstrip("v")
        match = _SEMVER_RE.match(cleaned)
        if not match:
            raise ValueError(f"Invalid semver string: {version_str!r}")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=match.group("prerelease"),
            build_metadata=match.group("build"),
        )

    def bump(self, bump_type: BumpType) -> VersionInfo:
        """Return a new VersionInfo with the appropriate field incremented."""
        if bump_type == BumpType.major:
            return VersionInfo(major=self.major + 1, minor=0, patch=0)
        if bump_type == BumpType.minor:
            return VersionInfo(major=self.major, minor=self.minor + 1, patch=0)
        return VersionInfo(major=self.major, minor=self.minor, patch=self.patch + 1)

    def _comparison_tuple(self) -> tuple[int, int, int, tuple[int, ...]]:
        """Return a tuple suitable for ordering comparisons.

        Versions without prerelease have higher precedence than those with one.
        """
        if self.prerelease is None:
            # No prerelease means higher precedence — use empty tuple with max sentinel
            return (self.major, self.minor, self.patch, (1,))
        # Prerelease identifiers compared numerically where possible
        parts: list[int] = []
        for part in self.prerelease.split("."):
            parts.append(int(part) if part.isdigit() else hash(part))
        return (self.major, self.minor, self.patch, (0, *parts))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return self._comparison_tuple() < other._comparison_tuple()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return self._comparison_tuple() <= other._comparison_tuple()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return self._comparison_tuple() > other._comparison_tuple()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return self._comparison_tuple() >= other._comparison_tuple()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.prerelease == other.prerelease
        )

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            version += f"-{self.prerelease}"
        if self.build_metadata:
            version += f"+{self.build_metadata}"
        return version


_VERSION_LINE_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)


class VersionManager:
    """Manages the version field in pyproject.toml."""

    def __init__(self, pyproject_path: Path) -> None:
        self._pyproject_path = pyproject_path

    def get_current_version(self) -> VersionInfo:
        """Read the current version from pyproject.toml."""
        content = self._pyproject_path.read_text(encoding="utf-8")
        match = _VERSION_LINE_RE.search(content)
        if not match:
            raise ValueError(f"No version field found in {self._pyproject_path}")
        version_str = content[match.start(1) + len(match.group(1)):match.start(2)]
        return VersionInfo.parse(version_str)

    def set_version(self, version: VersionInfo) -> None:
        """Update the version in pyproject.toml."""
        content = self._pyproject_path.read_text(encoding="utf-8")
        new_content = _VERSION_LINE_RE.sub(rf'\g<1>{version}\2', content, count=1)
        if new_content == content:
            raise ValueError(f"No version field found in {self._pyproject_path}")
        self._pyproject_path.write_text(new_content, encoding="utf-8")

    def bump_version(self, bump_type: BumpType) -> VersionInfo:
        """Bump the version and write it back. Returns the new version."""
        current = self.get_current_version()
        new_version = current.bump(bump_type)
        self.set_version(new_version)
        return new_version

    def get_version_tag(self, version: VersionInfo | None = None) -> str:
        """Return the git tag string for a version."""
        if version is None:
            version = self.get_current_version()
        return f"v{version}"
