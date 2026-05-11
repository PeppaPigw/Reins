"""File cleanup logic with manifest tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from reins.packaging.manifest import InstallManifest, ManifestEntry

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    removed_files: list[str] = field(default_factory=list)
    removed_dirs: list[str] = field(default_factory=list)
    skipped_modified: list[str] = field(default_factory=list)
    skipped_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CleanupEngine:
    """Removes tracked files and empty directories."""

    def __init__(self, repo_root: Path, manifest: InstallManifest) -> None:
        self._repo_root = repo_root
        self._manifest = manifest

    def plan_cleanup(self, force: bool = False) -> CleanupResult:
        """Dry-run: determine what would be removed."""
        result = CleanupResult()

        for entry in self._manifest.get_files():
            abs_path = self._repo_root / entry.path
            if not abs_path.exists():
                result.skipped_missing.append(entry.path)
                continue
            if not force and self._manifest.is_modified(entry):
                result.skipped_modified.append(entry.path)
                continue
            result.removed_files.append(entry.path)

        # Directories removed only if they would be empty after file removal
        removed_set = set(result.removed_files)
        for entry in self._manifest.get_directories():
            abs_path = self._repo_root / entry.path
            if not abs_path.exists():
                result.skipped_missing.append(entry.path)
                continue
            if self._would_be_empty(abs_path, removed_set):
                result.removed_dirs.append(entry.path)

        return result

    def execute_cleanup(self, force: bool = False) -> CleanupResult:
        """Remove files and empty directories, then remove the manifest itself."""
        result = CleanupResult()

        for entry in self._manifest.get_files():
            abs_path = self._repo_root / entry.path
            if not abs_path.exists():
                result.skipped_missing.append(entry.path)
                continue
            if not force and self._manifest.is_modified(entry):
                result.skipped_modified.append(entry.path)
                continue
            if self._remove_file(abs_path):
                result.removed_files.append(entry.path)
            else:
                result.errors.append(f"Failed to remove: {entry.path}")

        for entry in self._manifest.get_directories():
            abs_path = self._repo_root / entry.path
            if not abs_path.exists():
                result.skipped_missing.append(entry.path)
                continue
            if self._remove_empty_dir(abs_path):
                result.removed_dirs.append(entry.path)

        # Remove the manifest file itself
        manifest_path = self._repo_root / InstallManifest.MANIFEST_FILE
        if manifest_path.exists():
            self._remove_file(manifest_path)

        return result

    def _remove_file(self, path: Path) -> bool:
        """Remove a single file. Returns True on success."""
        try:
            path.unlink()
            return True
        except OSError as exc:
            logger.warning("Failed to remove file %s: %s", path, exc)
            return False

    def _remove_empty_dir(self, path: Path) -> bool:
        """Remove directory only if empty. Returns True on success."""
        try:
            if not any(path.iterdir()):
                path.rmdir()
                return True
            return False
        except OSError as exc:
            logger.warning("Failed to remove directory %s: %s", path, exc)
            return False

    def _would_be_empty(self, dir_path: Path, files_to_remove: set[str]) -> bool:
        """Check if directory would be empty after planned file removals."""
        try:
            for child in dir_path.rglob("*"):
                if child.is_file():
                    rel = str(child.relative_to(self._repo_root))
                    if rel not in files_to_remove:
                        return False
            return True
        except OSError:
            return False
