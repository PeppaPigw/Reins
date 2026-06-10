from __future__ import annotations

from collections import defaultdict

from reins.versioning.types import (
    BehaviorChange,
    BehaviorVersion,
    ChangeKind,
    CompatibilityLevel,
    Migration,
    MigrationStatus,
    SemanticVersion,
    VersioningStats,
)


class VersioningEngine:
    """Semantic versioning for agent behavior with compatibility checks.

    Tracks behavioral changes, auto-bumps versions based on change kind,
    checks compatibility between versions, and manages migrations.
    """

    def __init__(self) -> None:
        self._versions: dict[str, list[BehaviorVersion]] = defaultdict(list)
        self._changes: list[BehaviorChange] = []
        self._migrations: dict[str, Migration] = {}

    def get_current_version(self, agent_id: str) -> SemanticVersion:
        versions = self._versions.get(agent_id, [])
        if not versions:
            return SemanticVersion()
        return versions[-1].version

    def record_change(self, agent_id: str, kind: ChangeKind,
                      description: str, auto_bump: bool = True) -> BehaviorChange:
        current = self.get_current_version(agent_id)
        if auto_bump:
            new_version = self._bump_for_kind(current, kind)
        else:
            new_version = current

        change = BehaviorChange(
            agent_id=agent_id,
            kind=kind,
            description=description,
            from_version=str(current),
            to_version=str(new_version),
        )
        self._changes.append(change)

        if auto_bump and str(new_version) != str(current):
            bv = BehaviorVersion(
                agent_id=agent_id,
                version=new_version,
                changes=(change.change_id,),
            )
            self._versions[agent_id].append(bv)

        return change

    def release_version(self, agent_id: str, version: SemanticVersion,
                        change_ids: list[str] | None = None) -> BehaviorVersion:
        bv = BehaviorVersion(
            agent_id=agent_id,
            version=version,
            changes=tuple(change_ids or []),
        )
        self._versions[agent_id].append(bv)
        return bv

    def get_version_history(self, agent_id: str) -> list[BehaviorVersion]:
        return self._versions.get(agent_id, [])

    def check_compatibility(self, agent_id: str,
                            v1: SemanticVersion,
                            v2: SemanticVersion) -> CompatibilityLevel:
        if v1.major != v2.major:
            return CompatibilityLevel.INCOMPATIBLE
        if v1.minor != v2.minor:
            return CompatibilityLevel.BACKWARD_COMPATIBLE
        if v1.patch != v2.patch:
            return CompatibilityLevel.FULLY_COMPATIBLE
        return CompatibilityLevel.FULLY_COMPATIBLE

    def get_changes(self, agent_id: str | None = None,
                    kind: ChangeKind | None = None) -> list[BehaviorChange]:
        changes = self._changes
        if agent_id:
            changes = [c for c in changes if c.agent_id == agent_id]
        if kind:
            changes = [c for c in changes if c.kind == kind]
        return changes

    def create_migration(self, agent_id: str, from_version: str,
                         to_version: str, steps: list[str] | None = None) -> Migration:
        migration = Migration(
            agent_id=agent_id,
            from_version=from_version,
            to_version=to_version,
            steps=tuple(steps or []),
        )
        self._migrations[migration.migration_id] = migration
        return migration

    def get_migration(self, migration_id: str) -> Migration | None:
        return self._migrations.get(migration_id)

    def update_migration_status(self, migration_id: str,
                                status: MigrationStatus) -> Migration | None:
        migration = self._migrations.get(migration_id)
        if not migration:
            return None
        updated = Migration(
            migration_id=migration.migration_id,
            agent_id=migration.agent_id,
            from_version=migration.from_version,
            to_version=migration.to_version,
            status=status,
            steps=migration.steps,
            created_at=migration.created_at,
        )
        self._migrations[migration_id] = updated
        return updated

    def get_migrations(self, agent_id: str | None = None,
                       status: MigrationStatus | None = None) -> list[Migration]:
        migrations = list(self._migrations.values())
        if agent_id:
            migrations = [m for m in migrations if m.agent_id == agent_id]
        if status:
            migrations = [m for m in migrations if m.status == status]
        return migrations

    def get_stats(self) -> VersioningStats:
        agents = set()
        for agent_id in self._versions:
            if self._versions[agent_id]:
                agents.add(agent_id)

        by_kind: dict[str, int] = defaultdict(int)
        for c in self._changes:
            by_kind[c.kind.value] += 1

        by_status: dict[str, int] = defaultdict(int)
        for m in self._migrations.values():
            by_status[m.status.value] += 1

        total_versions = sum(len(v) for v in self._versions.values())

        return VersioningStats(
            total_agents=len(agents),
            total_versions=total_versions,
            total_changes=len(self._changes),
            total_migrations=len(self._migrations),
            by_change_kind=dict(by_kind),
            by_migration_status=dict(by_status),
        )

    def _bump_for_kind(self, current: SemanticVersion, kind: ChangeKind) -> SemanticVersion:
        if kind == ChangeKind.BREAKING:
            return current.bump_major()
        elif kind in (ChangeKind.FEATURE, ChangeKind.DEPRECATION):
            return current.bump_minor()
        else:
            return current.bump_patch()
