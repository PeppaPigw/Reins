from __future__ import annotations

from collections import defaultdict

from reins.behavior_versioning.types import (
    BehaviorBaseline,
    BehaviorDiff,
    BehaviorSignature,
    BehaviorVersioningStats,
    ChangeKind,
    DriftStatus,
)


class BehaviorVersioner:
    """Semantic versioning for agent behaviors.

    Captures behavioral signatures (action profiles, success rates, latency),
    detects drift from baselines, computes semantic diffs, and maintains
    version history. Enables rollback to known-good behavior patterns.
    """

    def __init__(self) -> None:
        self._baselines: dict[str, list[BehaviorBaseline]] = {}
        self._current: dict[str, BehaviorSignature] = {}
        self._diffs: list[BehaviorDiff] = []

    def capture_signature(self, agent_id: str,
                          action_profile: dict[str, int] | None = None,
                          success_rate: float = 1.0,
                          avg_latency_ms: float = 0.0,
                          resource_profile: dict[str, float] | None = None) -> BehaviorSignature:
        current = self._current.get(agent_id)
        version = self._next_version(agent_id) if not current else current.version

        sig = BehaviorSignature(
            agent_id=agent_id,
            version=version,
            action_profile=action_profile or {},
            success_rate=success_rate,
            avg_latency_ms=avg_latency_ms,
            resource_profile=resource_profile or {},
        )
        self._current[agent_id] = sig
        return sig

    def create_baseline(self, agent_id: str,
                        is_golden: bool = False) -> BehaviorBaseline | None:
        sig = self._current.get(agent_id)
        if not sig:
            return None

        baseline = BehaviorBaseline(
            agent_id=agent_id,
            version=sig.version,
            signature=sig,
            is_golden=is_golden,
        )
        if agent_id not in self._baselines:
            self._baselines[agent_id] = []
        self._baselines[agent_id].append(baseline)
        return baseline

    def get_baseline(self, agent_id: str,
                     version: str | None = None) -> BehaviorBaseline | None:
        baselines = self._baselines.get(agent_id, [])
        if not baselines:
            return None
        if version:
            return next((b for b in baselines if b.version == version), None)
        return baselines[-1]

    def get_golden_baseline(self, agent_id: str) -> BehaviorBaseline | None:
        baselines = self._baselines.get(agent_id, [])
        golden = [b for b in baselines if b.is_golden]
        return golden[-1] if golden else None

    def detect_drift(self, agent_id: str) -> DriftStatus:
        current = self._current.get(agent_id)
        baseline = self.get_golden_baseline(agent_id) or self.get_baseline(agent_id)
        if not current or not baseline:
            return DriftStatus.STABLE

        diff = self._compute_diff(baseline.signature, current)
        if diff.change_kind == ChangeKind.MAJOR:
            return DriftStatus.DIVERGED
        elif diff.change_kind == ChangeKind.MINOR:
            return DriftStatus.DRIFTING
        return DriftStatus.STABLE

    def compute_diff(self, agent_id: str) -> BehaviorDiff | None:
        current = self._current.get(agent_id)
        baseline = self.get_baseline(agent_id)
        if not current or not baseline:
            return None

        diff = self._compute_diff(baseline.signature, current)
        self._diffs.append(diff)
        return diff

    def bump_version(self, agent_id: str, kind: ChangeKind) -> str:
        current = self._current.get(agent_id)
        if not current:
            return "0.1.0"

        parts = current.version.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

        if kind == ChangeKind.MAJOR:
            major += 1
            minor = 0
            patch = 0
        elif kind == ChangeKind.MINOR:
            minor += 1
            patch = 0
        else:
            patch += 1

        new_version = f"{major}.{minor}.{patch}"
        self._current[agent_id] = current.model_copy(update={"version": new_version})
        return new_version

    def rollback(self, agent_id: str, version: str) -> BehaviorSignature | None:
        baseline = self.get_baseline(agent_id, version=version)
        if not baseline:
            return None
        self._current[agent_id] = baseline.signature
        return baseline.signature

    def get_history(self, agent_id: str) -> list[BehaviorBaseline]:
        return self._baselines.get(agent_id, [])

    def get_diffs(self, agent_id: str | None = None) -> list[BehaviorDiff]:
        if agent_id:
            return [d for d in self._diffs if d.agent_id == agent_id]
        return list(self._diffs)

    def get_stats(self) -> BehaviorVersioningStats:
        by_kind: dict[str, int] = defaultdict(int)
        for d in self._diffs:
            by_kind[d.change_kind.value] += 1

        by_drift: dict[str, int] = defaultdict(int)
        drifting = 0
        for agent_id in self._current:
            status = self.detect_drift(agent_id)
            by_drift[status.value] += 1
            if status != DriftStatus.STABLE:
                drifting += 1

        total_versions = sum(len(bl) for bl in self._baselines.values())

        return BehaviorVersioningStats(
            total_agents=len(self._current),
            total_versions=total_versions,
            total_diffs=len(self._diffs),
            agents_drifting=drifting,
            by_change_kind=dict(by_kind),
            by_drift_status=dict(by_drift),
        )

    def _next_version(self, agent_id: str) -> str:
        baselines = self._baselines.get(agent_id, [])
        if not baselines:
            return "0.1.0"
        last = baselines[-1].version
        parts = last.split(".")
        return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"

    def _compute_diff(self, old: BehaviorSignature,
                      new: BehaviorSignature) -> BehaviorDiff:
        old_actions = set(old.action_profile.keys())
        new_actions = set(new.action_profile.keys())
        added = sorted(new_actions - old_actions)
        removed = sorted(old_actions - new_actions)
        success_delta = new.success_rate - old.success_rate
        latency_delta = new.avg_latency_ms - old.avg_latency_ms

        if removed or abs(success_delta) > 0.2:
            kind = ChangeKind.MAJOR
        elif added or abs(success_delta) > 0.05:
            kind = ChangeKind.MINOR
        else:
            kind = ChangeKind.PATCH

        return BehaviorDiff(
            agent_id=new.agent_id,
            from_version=old.version,
            to_version=new.version,
            change_kind=kind,
            added_actions=added,
            removed_actions=removed,
            success_rate_delta=success_delta,
            latency_delta_ms=latency_delta,
        )
