from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from reins.conflicts.types import (
    Change,
    ChangeKind,
    Conflict,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    ResolutionStrategy,
)


_FUNCTION_MODIFY_KINDS = {
    ChangeKind.FUNCTION_MODIFIED,
    ChangeKind.FUNCTION_ADDED,
    ChangeKind.FUNCTION_REMOVED,
}

_DEPENDENCY_KINDS = {
    ChangeKind.DEPENDENCY_ADDED,
    ChangeKind.DEPENDENCY_REMOVED,
    ChangeKind.DEPENDENCY_VERSION_CHANGED,
}


class ConflictDetector:
    """Detects semantic conflicts between changes from multiple agents.

    Goes beyond git merge conflicts to identify logical incompatibilities:
    - Overlapping function modifications by different agents
    - Contradictory API signature changes
    - Incompatible dependency version requirements
    - Race conditions on shared mutable state
    - Semantic divergence (same symbol modified with different intent)
    """

    def __init__(self, overlap_line_threshold: int = 5) -> None:
        self._overlap_threshold = overlap_line_threshold

    async def detect(self, changes: list[Change]) -> ConflictReport:
        if len(changes) < 2:
            return ConflictReport(
                total_changes_analyzed=len(changes),
                agents_involved=tuple(sorted({c.agent_id for c in changes})),
            )

        conflicts: list[Conflict] = []

        by_file: dict[str, list[Change]] = defaultdict(list)
        by_symbol: dict[str, list[Change]] = defaultdict(list)
        by_dep: dict[str, list[Change]] = defaultdict(list)

        for change in changes:
            by_file[change.file_path].append(change)
            if change.symbol:
                by_symbol[change.symbol].append(change)
            if change.kind in _DEPENDENCY_KINDS:
                dep_name = change.symbol or change.metadata.get("package", "")
                if dep_name:
                    by_dep[dep_name].append(change)

        conflicts.extend(self._detect_overlapping_modifications(by_file))
        conflicts.extend(self._detect_api_conflicts(by_symbol))
        conflicts.extend(self._detect_dependency_conflicts(by_dep))
        conflicts.extend(self._detect_shared_state_races(by_file, changes))
        conflicts.extend(self._detect_deleted_dependencies(changes, by_symbol))

        agents = tuple(sorted({c.agent_id for c in changes}))
        has_critical = any(c.severity == ConflictSeverity.CRITICAL for c in conflicts)

        return ConflictReport(
            conflicts=tuple(conflicts),
            total_changes_analyzed=len(changes),
            agents_involved=agents,
            has_critical=has_critical,
        )

    def _detect_overlapping_modifications(
        self, by_file: dict[str, list[Change]]
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        for file_path, file_changes in by_file.items():
            agent_changes: dict[str, list[Change]] = defaultdict(list)
            for c in file_changes:
                agent_changes[c.agent_id].append(c)

            if len(agent_changes) < 2:
                continue

            agents = list(agent_changes.keys())
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    for ca in agent_changes[agents[i]]:
                        for cb in agent_changes[agents[j]]:
                            if self._ranges_overlap(ca.line_range, cb.line_range):
                                severity = self._overlap_severity(ca, cb)
                                conflicts.append(Conflict(
                                    conflict_type=ConflictType.OVERLAPPING_MODIFICATION,
                                    severity=severity,
                                    change_a=ca,
                                    change_b=cb,
                                    description=(
                                        f"Agents {ca.agent_id} and {cb.agent_id} both modify "
                                        f"overlapping regions in {file_path}"
                                    ),
                                    affected_symbols=tuple(
                                        filter(None, [ca.symbol, cb.symbol])
                                    ),
                                    suggested_resolution=ResolutionStrategy.MANUAL,
                                ))

        return conflicts

    def _detect_api_conflicts(
        self, by_symbol: dict[str, list[Change]]
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        for symbol, symbol_changes in by_symbol.items():
            sig_changes = [
                c for c in symbol_changes
                if c.kind == ChangeKind.API_SIGNATURE_CHANGED
            ]

            agent_sigs: dict[str, list[Change]] = defaultdict(list)
            for c in sig_changes:
                agent_sigs[c.agent_id].append(c)

            if len(agent_sigs) < 2:
                continue

            agents = list(agent_sigs.keys())
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    ca = agent_sigs[agents[i]][0]
                    cb = agent_sigs[agents[j]][0]
                    if ca.new_value != cb.new_value:
                        conflicts.append(Conflict(
                            conflict_type=ConflictType.CONTRADICTORY_API_CHANGE,
                            severity=ConflictSeverity.HIGH,
                            change_a=ca,
                            change_b=cb,
                            description=(
                                f"Contradictory API changes to {symbol}: "
                                f"agent {ca.agent_id} wants '{ca.new_value}' "
                                f"but agent {cb.agent_id} wants '{cb.new_value}'"
                            ),
                            affected_symbols=(symbol,),
                            suggested_resolution=ResolutionStrategy.MANUAL,
                        ))

        return conflicts

    def _detect_dependency_conflicts(
        self, by_dep: dict[str, list[Change]]
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        for dep_name, dep_changes in by_dep.items():
            agent_deps: dict[str, list[Change]] = defaultdict(list)
            for c in dep_changes:
                agent_deps[c.agent_id].append(c)

            if len(agent_deps) < 2:
                continue

            agents = list(agent_deps.keys())
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    ca = agent_deps[agents[i]][0]
                    cb = agent_deps[agents[j]][0]

                    if (
                        ca.kind == ChangeKind.DEPENDENCY_ADDED
                        and cb.kind == ChangeKind.DEPENDENCY_REMOVED
                    ) or (
                        ca.kind == ChangeKind.DEPENDENCY_REMOVED
                        and cb.kind == ChangeKind.DEPENDENCY_ADDED
                    ):
                        conflicts.append(Conflict(
                            conflict_type=ConflictType.INCOMPATIBLE_DEPENDENCY,
                            severity=ConflictSeverity.HIGH,
                            change_a=ca,
                            change_b=cb,
                            description=(
                                f"Agent {ca.agent_id} {ca.kind.value}s {dep_name} "
                                f"while agent {cb.agent_id} {cb.kind.value}s it"
                            ),
                            affected_symbols=(dep_name,),
                            suggested_resolution=ResolutionStrategy.MANUAL,
                        ))
                    elif (
                        ca.kind == ChangeKind.DEPENDENCY_VERSION_CHANGED
                        and cb.kind == ChangeKind.DEPENDENCY_VERSION_CHANGED
                        and ca.new_value != cb.new_value
                    ):
                        if not self._versions_compatible(ca.new_value, cb.new_value):
                            conflicts.append(Conflict(
                                conflict_type=ConflictType.INCOMPATIBLE_DEPENDENCY,
                                severity=ConflictSeverity.MEDIUM,
                                change_a=ca,
                                change_b=cb,
                                description=(
                                    f"Incompatible version requirements for {dep_name}: "
                                    f"{ca.new_value} vs {cb.new_value}"
                                ),
                                affected_symbols=(dep_name,),
                                suggested_resolution=ResolutionStrategy.PREFER_SECOND,
                            ))

        return conflicts

    def _detect_shared_state_races(
        self, by_file: dict[str, list[Change]], all_changes: list[Change]
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        state_patterns = re.compile(
            r"(global|shared|singleton|cache|registry|_instance|_state|_lock)"
        )

        state_changes: list[Change] = []
        for c in all_changes:
            if c.symbol and state_patterns.search(c.symbol.lower()):
                state_changes.append(c)
            elif c.new_value and state_patterns.search(c.new_value.lower()):
                state_changes.append(c)

        agent_state: dict[str, list[Change]] = defaultdict(list)
        for c in state_changes:
            agent_state[c.agent_id].append(c)

        if len(agent_state) < 2:
            return conflicts

        agents = list(agent_state.keys())
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                for ca in agent_state[agents[i]]:
                    for cb in agent_state[agents[j]]:
                        if ca.file_path == cb.file_path or ca.symbol == cb.symbol:
                            conflicts.append(Conflict(
                                conflict_type=ConflictType.SHARED_STATE_RACE,
                                severity=ConflictSeverity.CRITICAL,
                                change_a=ca,
                                change_b=cb,
                                description=(
                                    f"Potential race condition: agents {ca.agent_id} and "
                                    f"{cb.agent_id} both modify shared state "
                                    f"'{ca.symbol or ca.file_path}'"
                                ),
                                affected_symbols=tuple(
                                    filter(None, [ca.symbol, cb.symbol])
                                ),
                                suggested_resolution=ResolutionStrategy.MANUAL,
                            ))

        return conflicts

    def _detect_deleted_dependencies(
        self, all_changes: list[Change], by_symbol: dict[str, list[Change]]
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []

        removed_symbols: dict[str, Change] = {}
        for c in all_changes:
            if c.kind == ChangeKind.FUNCTION_REMOVED and c.symbol:
                removed_symbols[c.symbol] = c

        for symbol, removal in removed_symbols.items():
            if symbol in by_symbol:
                users = [
                    c for c in by_symbol[symbol]
                    if c.agent_id != removal.agent_id
                    and c.kind not in {ChangeKind.FUNCTION_REMOVED}
                ]
                for user_change in users:
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.DELETED_DEPENDENCY,
                        severity=ConflictSeverity.HIGH,
                        change_a=removal,
                        change_b=user_change,
                        description=(
                            f"Agent {removal.agent_id} removes '{symbol}' "
                            f"but agent {user_change.agent_id} modifies/uses it"
                        ),
                        affected_symbols=(symbol,),
                        suggested_resolution=ResolutionStrategy.MANUAL,
                    ))

        return conflicts

    def _ranges_overlap(
        self,
        range_a: tuple[int, int] | None,
        range_b: tuple[int, int] | None,
    ) -> bool:
        if range_a is None or range_b is None:
            return False
        start_a, end_a = range_a
        start_b, end_b = range_b
        return not (end_a < start_b - self._overlap_threshold
                    or end_b < start_a - self._overlap_threshold)

    def _overlap_severity(self, ca: Change, cb: Change) -> ConflictSeverity:
        if ca.kind in _FUNCTION_MODIFY_KINDS and cb.kind in _FUNCTION_MODIFY_KINDS:
            if ca.symbol and ca.symbol == cb.symbol:
                return ConflictSeverity.HIGH
            return ConflictSeverity.MEDIUM
        return ConflictSeverity.LOW

    def _versions_compatible(
        self, version_a: str | None, version_b: str | None
    ) -> bool:
        if not version_a or not version_b:
            return True
        parts_a = self._parse_version(version_a)
        parts_b = self._parse_version(version_b)
        if not parts_a or not parts_b:
            return version_a == version_b
        return parts_a[0] == parts_b[0]

    def _parse_version(self, version: str) -> tuple[int, ...] | None:
        cleaned = re.sub(r"[^0-9.]", "", version)
        parts = cleaned.split(".")
        try:
            return tuple(int(p) for p in parts if p)
        except ValueError:
            return None
