"""Template hash tracking for platform templates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def sha256_text(content: str) -> str:
    """Return a SHA256 hash for text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_path(path: Path) -> str:
    """Return a SHA256 hash for a file on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class TemplateHashRecord:
    """Hash record for an installed template."""

    template_path: str
    template_hash: str
    rendered_hash: str


class TemplateHashStore:
    """Persist hashes for installed templates under `.reins/`."""

    def __init__(self, repo_root: Path, store_path: Path | None = None) -> None:
        self.repo_root = repo_root
        self.path = store_path or repo_root / ".reins" / ".template-hashes.json"

    def load(self) -> dict[str, TemplateHashRecord]:
        """Load all hash records."""
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            key: TemplateHashRecord(**value)
            for key, value in raw.items()
        }

    def save(self, records: dict[str, TemplateHashRecord]) -> None:
        """Save all hash records."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in records.items()}
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _key(self, target_path: Path) -> str:
        return str(target_path.resolve().relative_to(self.repo_root.resolve()))

    def get(self, target_path: Path) -> TemplateHashRecord | None:
        """Get a record for a target path."""
        return self.load().get(self._key(target_path))

    def update(
        self,
        *,
        target_path: Path,
        template_path: Path,
        template_hash: str,
        rendered_hash: str,
    ) -> None:
        """Update a single template hash record."""
        records = self.load()
        records[self._key(target_path)] = TemplateHashRecord(
            template_path=str(template_path),
            template_hash=template_hash,
            rendered_hash=rendered_hash,
        )
        self.save(records)

    def remove(self, target_path: Path) -> None:
        """Remove a record for a target path."""
        records = self.load()
        key = self._key(target_path)
        if key in records:
            del records[key]
            self.save(records)

    def has_customization(self, target_path: Path) -> bool:
        """Return True when the file was modified after template install."""
        record = self.get(target_path)
        if record is None or not target_path.exists():
            return target_path.exists()
        return sha256_path(target_path) != record.rendered_hash
