"""Semantic version helpers for declarative migrations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class SemanticVersion:
    """Minimal semantic version value object."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> SemanticVersion:
        parts = value.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise ValueError(f"Invalid semantic version: {value}")
        return cls(int(parts[0]), int(parts[1]), int(parts[2]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def sort_versions(versions: list[str]) -> list[str]:
    """Sort semantic versions from lowest to highest."""
    return [str(version) for version in sorted(SemanticVersion.parse(item) for item in versions)]


def versions_in_range(
    versions: list[str],
    *,
    from_version: str | None,
    to_version: str | None,
) -> list[str]:
    """Return versions where from_version < version <= to_version."""
    lower = SemanticVersion.parse(from_version) if from_version is not None else None
    upper = SemanticVersion.parse(to_version) if to_version is not None else None
    selected: list[str] = []
    for version in sort_versions(versions):
        parsed = SemanticVersion.parse(version)
        if lower is not None and parsed <= lower:
            continue
        if upper is not None and parsed > upper:
            continue
        selected.append(version)
    return selected
