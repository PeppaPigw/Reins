"""Declarative migration engine for Reins template and file updates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.migration.types import Migration, MigrationManifest
from reins.migration.version import SemanticVersion, versions_in_range


@dataclass(frozen=True)
class MigrationOperationResult:
    """Outcome of a single migration operation."""

    version: str
    migration_type: str
    description: str
    status: str
    from_path: str | None = None
    to_path: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _RollbackAction:
    action: str
    source: Path
    destination: Path | None = None
    backup: bytes | None = None


class MigrationEngine:
    """Loads, filters, validates, and applies declarative migration manifests."""

    def __init__(
        self,
        *,
        repo_root: Path,
        journal: EventJournal,
        run_id: str,
        manifest_dir: Path | None = None,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._journal = journal
        self._run_id = run_id
        self._builder = EventBuilder(journal)
        self._manifest_dir = (manifest_dir or self._repo_root / "migrations" / "manifests").resolve()
        self._schema_path = self._manifest_dir / "schema.json"

    def load_manifests(self) -> list[MigrationManifest]:
        """Load and sort all available manifests."""
        manifests: list[MigrationManifest] = []
        if not self._manifest_dir.exists():
            return manifests
        for manifest_path in sorted(self._manifest_dir.glob("*.json")):
            if manifest_path.name == "schema.json":
                continue
            manifests.append(self.load_manifest(manifest_path))
        manifests.sort(key=lambda manifest: SemanticVersion.parse(manifest.version))
        return manifests

    def load_manifest(self, path: Path) -> MigrationManifest:
        """Load and validate a single manifest."""
        schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
        data = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
        return MigrationManifest.from_dict(data)

    def manifests_between(
        self,
        *,
        from_version: str | None,
        to_version: str | None,
    ) -> list[MigrationManifest]:
        """Return manifests in the requested version range."""
        manifests = self.load_manifests()
        selected_versions = set(
            versions_in_range(
                [manifest.version for manifest in manifests],
                from_version=from_version,
                to_version=to_version,
            )
        )
        return [manifest for manifest in manifests if manifest.version in selected_versions]

    async def migrate(
        self,
        *,
        from_version: str | None,
        to_version: str | None,
        dry_run: bool = False,
    ) -> list[MigrationOperationResult]:
        """Apply migrations between two versions."""
        manifests = self.manifests_between(from_version=from_version, to_version=to_version)
        await self._builder.commit(
            run_id=self._run_id,
            event_type="migration.started",
            payload={
                "from_version": from_version,
                "to_version": to_version,
                "dry_run": dry_run,
                "manifest_count": len(manifests),
            },
        )

        results: list[MigrationOperationResult] = []
        rollback_actions: list[tuple[MigrationOperationResult, _RollbackAction]] = []

        try:
            for manifest in manifests:
                for migration in manifest.migrations:
                    result, rollback_action = await self._apply_migration(
                        manifest.version,
                        migration,
                        dry_run=dry_run,
                    )
                    results.append(result)
                    await self._emit_operation_event(result)
                    if rollback_action is not None:
                        rollback_actions.append((result, rollback_action))
        except Exception as exc:
            if not dry_run:
                rollback_results = await self._rollback(rollback_actions)
                results.extend(rollback_results)
            await self._builder.commit(
                run_id=self._run_id,
                event_type="migration.failed",
                payload={
                    "from_version": from_version,
                    "to_version": to_version,
                    "dry_run": dry_run,
                    "error": str(exc),
                },
            )
            raise

        await self._builder.commit(
            run_id=self._run_id,
            event_type="migration.completed",
            payload={
                "from_version": from_version,
                "to_version": to_version,
                "dry_run": dry_run,
                "result_count": len(results),
            },
        )
        return results

    async def _apply_migration(
        self,
        version: str,
        migration: Migration,
        *,
        dry_run: bool,
    ) -> tuple[MigrationOperationResult, _RollbackAction | None]:
        if migration.type == "rename":
            return await self._apply_rename(version, migration, dry_run=dry_run)
        if migration.type == "delete":
            return await self._apply_delete(version, migration, dry_run=dry_run, safe=False)
        if migration.type == "safe-file-delete":
            return await self._apply_delete(version, migration, dry_run=dry_run, safe=True)
        if migration.type == "rename-dir":
            return await self._apply_rename_dir(version, migration, dry_run=dry_run)
        raise ValueError(f"Unsupported migration type: {migration.type}")

    async def _apply_rename(
        self,
        version: str,
        migration: Migration,
        *,
        dry_run: bool,
    ) -> tuple[MigrationOperationResult, _RollbackAction | None]:
        source = self._resolve_path(migration.from_path)
        target = self._resolve_path(migration.to_path)
        if not source.exists():
            reason = "already_applied" if target.exists() else "missing_source"
            return self._result(version, migration, "skipped", reason=reason), None
        if target.exists():
            raise RuntimeError(
                f"Cannot rename {migration.from_path} to {migration.to_path}: target exists"
            )
        if dry_run:
            return self._result(version, migration, "dry_run"), None
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(source), str(target))
        return self._result(version, migration, "applied"), _RollbackAction(
            action="rename",
            source=target,
            destination=source,
        )

    async def _apply_delete(
        self,
        version: str,
        migration: Migration,
        *,
        dry_run: bool,
        safe: bool,
    ) -> tuple[MigrationOperationResult, _RollbackAction | None]:
        source = self._resolve_path(migration.from_path)
        if not source.exists():
            return self._result(version, migration, "skipped", reason="missing_source"), None
        if source.is_dir():
            raise RuntimeError(f"Delete migration only supports files: {migration.from_path}")
        if safe:
            digest = await asyncio.to_thread(self._sha256, source)
            if digest not in migration.allowed_hashes:
                return self._result(version, migration, "skipped", reason="hash_mismatch"), None
        if dry_run:
            return self._result(version, migration, "dry_run"), None
        backup = await asyncio.to_thread(source.read_bytes)
        await asyncio.to_thread(source.unlink)
        return self._result(version, migration, "applied"), _RollbackAction(
            action="restore-file",
            source=source,
            backup=backup,
        )

    async def _apply_rename_dir(
        self,
        version: str,
        migration: Migration,
        *,
        dry_run: bool,
    ) -> tuple[MigrationOperationResult, _RollbackAction | None]:
        source = self._resolve_path(migration.from_path)
        target = self._resolve_path(migration.to_path)
        if not source.exists():
            reason = "already_applied" if target.exists() else "missing_source"
            return self._result(version, migration, "skipped", reason=reason), None
        if not source.is_dir():
            raise RuntimeError(f"rename-dir source is not a directory: {migration.from_path}")
        if target.exists():
            raise RuntimeError(
                f"Cannot rename directory {migration.from_path} to {migration.to_path}: target exists"
            )
        if dry_run:
            return self._result(version, migration, "dry_run"), None
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(source), str(target))
        return self._result(version, migration, "applied"), _RollbackAction(
            action="rename-dir",
            source=target,
            destination=source,
        )

    async def _rollback(
        self,
        rollback_actions: list[tuple[MigrationOperationResult, _RollbackAction]],
    ) -> list[MigrationOperationResult]:
        rollback_results: list[MigrationOperationResult] = []
        for applied_result, action in reversed(rollback_actions):
            await self._execute_rollback(action)
            result = MigrationOperationResult(
                version=applied_result.version,
                migration_type=applied_result.migration_type,
                description=applied_result.description,
                status="rolled_back",
                from_path=applied_result.from_path,
                to_path=applied_result.to_path,
            )
            rollback_results.append(result)
            await self._emit_operation_event(result)
        return rollback_results

    async def _execute_rollback(self, action: _RollbackAction) -> None:
        if action.action in {"rename", "rename-dir"}:
            if action.source.exists() and action.destination is not None:
                action.destination.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.move, str(action.source), str(action.destination))
            return
        if action.action == "restore-file" and action.backup is not None:
            action.source.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(action.source.write_bytes, action.backup)
            return
        raise RuntimeError(f"Unsupported rollback action: {action.action}")

    async def _emit_operation_event(self, result: MigrationOperationResult) -> None:
        await self._builder.commit(
            run_id=self._run_id,
            event_type="migration.operation",
            payload={
                "version": result.version,
                "migration_type": result.migration_type,
                "description": result.description,
                "status": result.status,
                "from_path": result.from_path,
                "to_path": result.to_path,
                "reason": result.reason,
            },
        )

    def _resolve_path(self, raw_path: str | None) -> Path:
        if raw_path is None:
            raise ValueError("Migration path is required")
        resolved = (self._repo_root / raw_path).resolve()
        if self._repo_root not in resolved.parents and resolved != self._repo_root:
            raise ValueError(f"Migration path escapes repo root: {raw_path}")
        return resolved

    def _result(
        self,
        version: str,
        migration: Migration,
        status: str,
        *,
        reason: str | None = None,
    ) -> MigrationOperationResult:
        return MigrationOperationResult(
            version=version,
            migration_type=migration.type,
            description=migration.description,
            status=status,
            from_path=migration.from_path,
            to_path=migration.to_path,
            reason=reason,
        )

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
