"""Typed declarative migration manifests."""

from __future__ import annotations

from dataclasses import dataclass, field

from reins.migration.version import SemanticVersion

VALID_MIGRATION_TYPES = {"rename", "delete", "safe-file-delete", "rename-dir"}


@dataclass(frozen=True)
class Migration:
    """A single declarative filesystem migration operation."""

    type: str
    from_path: str | None = None
    to_path: str | None = None
    allowed_hashes: list[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in VALID_MIGRATION_TYPES:
            raise ValueError(
                f"Invalid migration type '{self.type}'. Expected one of: {sorted(VALID_MIGRATION_TYPES)}"
            )
        if not self.description:
            raise ValueError("Migration description is required")
        if self.type in {"rename", "rename-dir"}:
            if not self.from_path or not self.to_path:
                raise ValueError(f"{self.type} requires from_path and to_path")
        if self.type in {"delete", "safe-file-delete"} and not self.from_path:
            raise ValueError(f"{self.type} requires from_path")
        if self.type == "safe-file-delete" and not self.allowed_hashes:
            raise ValueError("safe-file-delete requires allowed_hashes")

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Migration:
        raw_hashes = data.get("allowed_hashes", [])
        allowed_hashes = (
            [str(item) for item in raw_hashes if isinstance(item, str)]
            if isinstance(raw_hashes, list)
            else []
        )
        return cls(
            type=str(data["type"]),
            from_path=str(data["from_path"]) if data.get("from_path") is not None else None,
            to_path=str(data["to_path"]) if data.get("to_path") is not None else None,
            allowed_hashes=allowed_hashes,
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class MigrationManifest:
    """A versioned collection of declarative migrations."""

    version: str
    migrations: list[Migration]

    def __post_init__(self) -> None:
        SemanticVersion.parse(self.version)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MigrationManifest:
        migrations_raw = data.get("migrations", [])
        if not isinstance(migrations_raw, list):
            raise ValueError("Manifest migrations must be a list")
        return cls(
            version=str(data["version"]),
            migrations=[
                Migration.from_dict(item)
                for item in migrations_raw
                if isinstance(item, dict)
            ],
        )
