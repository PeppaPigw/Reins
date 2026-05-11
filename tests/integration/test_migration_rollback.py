"""Integration tests for migration rollback: execution, rollback, dry-run, version filtering."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reins.kernel.event.journal import EventJournal
from reins.migration.engine import MigrationEngine, MigrationOperationResult
from reins.migration.types import Migration, MigrationManifest


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _make_journal(tmp_path: Path) -> EventJournal:
    """Create a journal for migration event tracking."""
    journal_path = tmp_path / "journal.jsonl"
    journal_path.touch()
    return EventJournal(journal_path)


def _make_engine(
    tmp_path: Path,
    journal: EventJournal,
    manifest_dir: Path | None = None,
) -> MigrationEngine:
    """Create a MigrationEngine pointed at tmp_path."""
    return MigrationEngine(
        repo_root=tmp_path,
        journal=journal,
        run_id="test-run-001",
        manifest_dir=manifest_dir or tmp_path / "migrations" / "manifests",
    )


async def _apply_single(
    engine: MigrationEngine,
    version: str,
    migration: Migration,
    *,
    dry_run: bool = False,
) -> tuple[MigrationOperationResult, object]:
    """Helper to apply a single migration operation."""
    return await engine._apply_migration(version, migration, dry_run=dry_run)


async def _run_migrate_with_manifests(
    engine: MigrationEngine,
    manifests: list[MigrationManifest],
    *,
    from_version: str | None = None,
    to_version: str | None = None,
    dry_run: bool = False,
) -> list[MigrationOperationResult]:
    """Run migrate with patched manifests_between to avoid needing schema.json."""
    with patch.object(engine, "manifests_between", return_value=manifests):
        return await engine.migrate(
            from_version=from_version,
            to_version=to_version,
            dry_run=dry_run,
        )


# ---------------------------------------------------------------------------
# TestMigrationExecution
# ---------------------------------------------------------------------------


class TestMigrationExecution:
    """Tests for individual migration operation types."""

    def test_rename_migration_moves_file(self, tmp_path: Path) -> None:
        """A rename migration should move source to destination."""
        source = tmp_path / "old_config.yaml"
        source.write_text("key: value\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="rename",
            from_path="old_config.yaml",
            to_path="new_config.yaml",
            description="Rename config file",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "applied"
        assert not source.exists()
        assert (tmp_path / "new_config.yaml").exists()
        assert (tmp_path / "new_config.yaml").read_text(encoding="utf-8") == "key: value\n"

    def test_delete_migration_removes_file(self, tmp_path: Path) -> None:
        """A delete migration should remove the target file."""
        target = tmp_path / "deprecated.txt"
        target.write_text("old content\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="delete",
            from_path="deprecated.txt",
            description="Remove deprecated file",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "applied"
        assert not target.exists()

    def test_safe_delete_checks_hash(self, tmp_path: Path) -> None:
        """safe-file-delete should only remove if hash matches."""
        content = b"known content\n"
        target = tmp_path / "managed.txt"
        target.write_bytes(content)
        correct_hash = _sha256(content)

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="safe-file-delete",
            from_path="managed.txt",
            allowed_hashes=[correct_hash],
            description="Safe delete with hash check",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "applied"
        assert not target.exists()

    def test_safe_delete_refuses_wrong_hash(self, tmp_path: Path) -> None:
        """safe-file-delete should skip if hash does not match."""
        target = tmp_path / "managed.txt"
        target.write_text("actual content\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="safe-file-delete",
            from_path="managed.txt",
            allowed_hashes=["0000000000000000000000000000000000000000000000000000000000000000"],
            description="Safe delete with wrong hash",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "skipped"
        assert result.reason == "hash_mismatch"
        assert target.exists()

    def test_rename_dir_migration(self, tmp_path: Path) -> None:
        """rename-dir should move an entire directory."""
        old_dir = tmp_path / "old_dir"
        old_dir.mkdir()
        (old_dir / "file1.txt").write_text("content1\n", encoding="utf-8")
        (old_dir / "file2.txt").write_text("content2\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="rename-dir",
            from_path="old_dir",
            to_path="new_dir",
            description="Rename directory",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "applied"
        assert not old_dir.exists()
        new_dir = tmp_path / "new_dir"
        assert new_dir.is_dir()
        assert (new_dir / "file1.txt").read_text(encoding="utf-8") == "content1\n"
        assert (new_dir / "file2.txt").read_text(encoding="utf-8") == "content2\n"

    def test_rename_skips_already_applied(self, tmp_path: Path) -> None:
        """Rename should skip if source is gone and target exists."""
        # Only the target exists (migration already applied)
        (tmp_path / "new_config.yaml").write_text("migrated\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        migration = Migration(
            type="rename",
            from_path="old_config.yaml",
            to_path="new_config.yaml",
            description="Already applied rename",
        )

        result, _ = asyncio.run(_apply_single(engine, "0.2.0", migration))

        assert result.status == "skipped"
        assert result.reason == "already_applied"


# ---------------------------------------------------------------------------
# TestMigrationRollback
# ---------------------------------------------------------------------------


class TestMigrationRollback:
    """Tests for rollback behavior when migrations fail."""

    def test_rollback_on_failure_restores_renamed_file(self, tmp_path: Path) -> None:
        """If second operation fails, first rename should be rolled back."""
        # Create file A (will be renamed to B)
        file_a = tmp_path / "file_a.txt"
        file_a.write_text("content A\n", encoding="utf-8")
        # file C does NOT exist — second rename will fail

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="rename",
                    from_path="file_a.txt",
                    to_path="file_b.txt",
                    description="Rename A to B",
                ),
                Migration(
                    type="rename",
                    from_path="file_c.txt",
                    to_path="file_d.txt",
                    description="Rename C to D (will fail - missing source)",
                ),
            ],
        )

        # The second rename will be skipped (missing source), not raise.
        # To trigger a real failure, we need target to already exist.
        # Let's create file_d so the rename of C->D raises RuntimeError
        # Actually, if C doesn't exist, it's skipped. Let's make C exist but D exist too.
        (tmp_path / "file_c.txt").write_text("content C\n", encoding="utf-8")
        (tmp_path / "file_d.txt").write_text("blocking\n", encoding="utf-8")

        # Now rename C->D will raise because target exists
        with pytest.raises(RuntimeError, match="target exists"):
            asyncio.run(
                _run_migrate_with_manifests(engine, [manifest], from_version="0.1.0", to_version="0.2.0")
            )

        # Rollback should have restored A
        assert file_a.exists()
        assert file_a.read_text(encoding="utf-8") == "content A\n"
        # B should not exist (rolled back)
        assert not (tmp_path / "file_b.txt").exists()

    def test_rollback_on_failure_restores_deleted_file(self, tmp_path: Path) -> None:
        """If a later operation fails, deleted files should be restored."""
        # Create file A (will be deleted)
        file_a = tmp_path / "file_a.txt"
        file_a.write_text("precious content\n", encoding="utf-8")
        # Create blocking condition for second op
        (tmp_path / "file_b.txt").write_text("source\n", encoding="utf-8")
        (tmp_path / "file_c.txt").write_text("blocker\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="delete",
                    from_path="file_a.txt",
                    description="Delete A",
                ),
                Migration(
                    type="rename",
                    from_path="file_b.txt",
                    to_path="file_c.txt",
                    description="Rename B to C (will fail - target exists)",
                ),
            ],
        )

        with pytest.raises(RuntimeError, match="target exists"):
            asyncio.run(
                _run_migrate_with_manifests(engine, [manifest], from_version="0.1.0", to_version="0.2.0")
            )

        # Rollback should have restored the deleted file
        assert file_a.exists()
        assert file_a.read_text(encoding="utf-8") == "precious content\n"

    def test_dry_run_makes_no_changes(self, tmp_path: Path) -> None:
        """Dry-run should report operations without modifying files."""
        source = tmp_path / "config.yaml"
        source.write_text("original\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="rename",
                    from_path="config.yaml",
                    to_path="config_v2.yaml",
                    description="Rename config",
                ),
            ],
        )

        results = asyncio.run(
            _run_migrate_with_manifests(
                engine, [manifest], from_version="0.1.0", to_version="0.2.0", dry_run=True
            )
        )

        assert len(results) == 1
        assert results[0].status == "dry_run"
        # File should be unchanged
        assert source.exists()
        assert not (tmp_path / "config_v2.yaml").exists()

    def test_version_range_filtering(self, tmp_path: Path) -> None:
        """Only manifests in the requested version range should be applied."""
        # Create files for each version's migration
        (tmp_path / "v1_file.txt").write_text("v1\n", encoding="utf-8")
        (tmp_path / "v2_file.txt").write_text("v2\n", encoding="utf-8")
        (tmp_path / "v3_file.txt").write_text("v3\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifests = [
            MigrationManifest(
                version="0.1.0",
                migrations=[
                    Migration(
                        type="delete",
                        from_path="v1_file.txt",
                        description="Delete v1 file",
                    ),
                ],
            ),
            MigrationManifest(
                version="0.2.0",
                migrations=[
                    Migration(
                        type="delete",
                        from_path="v2_file.txt",
                        description="Delete v2 file",
                    ),
                ],
            ),
            MigrationManifest(
                version="0.3.0",
                migrations=[
                    Migration(
                        type="delete",
                        from_path="v3_file.txt",
                        description="Delete v3 file",
                    ),
                ],
            ),
        ]

        # Migrate from 0.1.0 to 0.3.0 — should apply 0.2.0 and 0.3.0 only
        # (versions_in_range: from_version < version <= to_version)
        # We patch manifests_between to return only the filtered set
        from reins.migration.version import versions_in_range

        all_versions = [m.version for m in manifests]
        selected = set(
            versions_in_range(all_versions, from_version="0.1.0", to_version="0.3.0")
        )
        filtered = [m for m in manifests if m.version in selected]

        results = asyncio.run(
            _run_migrate_with_manifests(
                engine, filtered, from_version="0.1.0", to_version="0.3.0"
            )
        )

        # v1_file should still exist (0.1.0 not in range)
        assert (tmp_path / "v1_file.txt").exists()
        # v2 and v3 should be deleted
        assert not (tmp_path / "v2_file.txt").exists()
        assert not (tmp_path / "v3_file.txt").exists()
        assert len(results) == 2


# ---------------------------------------------------------------------------
# TestMigrationEvents
# ---------------------------------------------------------------------------


class TestMigrationEvents:
    """Tests for migration event emission."""

    def test_migration_emits_events(self, tmp_path: Path) -> None:
        """Running a migration should emit events to the journal."""
        source = tmp_path / "old.txt"
        source.write_text("data\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="rename",
                    from_path="old.txt",
                    to_path="new.txt",
                    description="Rename old to new",
                ),
            ],
        )

        asyncio.run(
            _run_migrate_with_manifests(engine, [manifest], from_version="0.1.0", to_version="0.2.0")
        )

        # Read journal and verify events were emitted
        journal_content = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
        lines = [line for line in journal_content.strip().split("\n") if line]
        event_types = [json.loads(line)["type"] for line in lines]

        assert "migration.started" in event_types
        assert "migration.operation" in event_types
        assert "migration.completed" in event_types

    def test_migration_result_includes_all_operations(self, tmp_path: Path) -> None:
        """Result should have an entry for each migration operation."""
        (tmp_path / "file1.txt").write_text("1\n", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("2\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="delete",
                    from_path="file1.txt",
                    description="Delete file1",
                ),
                Migration(
                    type="delete",
                    from_path="file2.txt",
                    description="Delete file2",
                ),
            ],
        )

        results = asyncio.run(
            _run_migrate_with_manifests(engine, [manifest], from_version="0.1.0", to_version="0.2.0")
        )

        assert len(results) == 2
        assert all(r.status == "applied" for r in results)
        assert results[0].description == "Delete file1"
        assert results[1].description == "Delete file2"

    def test_migration_skips_already_applied(self, tmp_path: Path) -> None:
        """A migration that was already applied should be skipped."""
        # Target already exists, source does not — rename is already applied
        (tmp_path / "new_name.txt").write_text("migrated\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifest = MigrationManifest(
            version="0.2.0",
            migrations=[
                Migration(
                    type="rename",
                    from_path="old_name.txt",
                    to_path="new_name.txt",
                    description="Already applied rename",
                ),
            ],
        )

        results = asyncio.run(
            _run_migrate_with_manifests(engine, [manifest], from_version="0.1.0", to_version="0.2.0")
        )

        assert len(results) == 1
        assert results[0].status == "skipped"
        assert results[0].reason == "already_applied"
        # File should remain untouched
        assert (tmp_path / "new_name.txt").read_text(encoding="utf-8") == "migrated\n"

    def test_multiple_manifests_applied_in_order(self, tmp_path: Path) -> None:
        """Multiple manifests should be applied in version order."""
        (tmp_path / "step1.txt").write_text("step1\n", encoding="utf-8")

        journal = _make_journal(tmp_path)
        engine = _make_engine(tmp_path, journal)

        manifests = [
            MigrationManifest(
                version="0.2.0",
                migrations=[
                    Migration(
                        type="rename",
                        from_path="step1.txt",
                        to_path="step2.txt",
                        description="Step 1 to 2",
                    ),
                ],
            ),
            MigrationManifest(
                version="0.3.0",
                migrations=[
                    Migration(
                        type="rename",
                        from_path="step2.txt",
                        to_path="step3.txt",
                        description="Step 2 to 3",
                    ),
                ],
            ),
        ]

        results = asyncio.run(
            _run_migrate_with_manifests(
                engine, manifests, from_version="0.1.0", to_version="0.3.0"
            )
        )

        assert len(results) == 2
        assert not (tmp_path / "step1.txt").exists()
        assert not (tmp_path / "step2.txt").exists()
        assert (tmp_path / "step3.txt").exists()
        assert (tmp_path / "step3.txt").read_text(encoding="utf-8") == "step1\n"
