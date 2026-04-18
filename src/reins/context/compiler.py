"""Context compilation primitives.

This module now serves two roles:

1. Legacy working-set compilation used by the existing orchestrator and tests.
2. Phase 6A multi-source compilation with optimization and TTL caching.

The legacy APIs are intentionally preserved so existing behavior remains stable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from fnmatch import fnmatch
from hashlib import sha256
from pathlib import Path
from typing import Any, Awaitable

import aiofiles  # type: ignore[import-untyped]

from reins.context.cache import ContextCache
from reins.context.optimizer import ContextOptimizer
from reins.context.types import LAYER_PRIORITY, SpecLayer
from reins.kernel.event.envelope import event_from_dict
from reins.kernel.event.journal import EventJournal
from reins.serde import canonical_json, parse_dt
from reins.task.projection import TaskContextProjection


@dataclass(frozen=True)
class ContextShard:
    """One slice of compiled legacy context."""

    tier: str
    source: str
    content: str
    token_estimate: int
    priority: float


@dataclass
class WorkingSet:
    """Legacy compiled working-set payload for one model turn."""

    run_id: str
    shards: list[ContextShard] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    dropped: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextSource:
    """One input source for the Phase 6A multi-source compiler."""

    type: str
    identifier: str | None = None
    path: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    event_types: list[str] = field(default_factory=list)
    content: str | None = None
    priority: float = 50.0
    metadata: dict[str, Any] = field(default_factory=dict)
    from_time: datetime | str | None = None
    to_time: datetime | str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class ContextSection:
    """One resolved section in the multi-source compiled context."""

    source_type: str
    identifier: str
    content: str
    token_count: int
    priority: float
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False


@dataclass(frozen=True)
class CompiledContext:
    """Compiled multi-source context payload."""

    sections: list[ContextSection]
    total_tokens: int
    max_tokens: int
    sources: list[str]
    dropped: list[str] = field(default_factory=list)
    deduplicated: list[str] = field(default_factory=list)
    cache_key: str | None = None
    cache_hit: bool = False
    optimized: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_text(self) -> str:
        chunks: list[str] = []
        for section in self.sections:
            chunks.append(f"## {section.source_type}: {section.identifier}\n")
            chunks.append(section.content.strip())
            chunks.append("\n\n")
        return "".join(chunks).strip()


def _estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token estimate."""
    return max(1, len(text) // 4)


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return parse_dt(value)


class ContextCompiler:
    """Legacy + multi-source context compiler."""

    def __init__(
        self,
        token_budget: int = 120_000,
        *,
        journal: EventJournal | None = None,
        task_projection: TaskContextProjection | None = None,
        optimizer: ContextOptimizer | None = None,
        cache: ContextCache | None = None,
    ) -> None:
        self.token_budget = token_budget
        self._standing_law: list[ContextShard] = []
        self._folded: list[ContextShard] = []
        self._journal = journal
        self._task_projection = task_projection
        self._optimizer = optimizer if optimizer is not None else ContextOptimizer()
        self._cache = cache if cache is not None else ContextCache()

    def resolve_spec_sources(
        self,
        spec_root: Path,
        *,
        task_type: str,
        package: str | None = None,
    ) -> list[ContextSource]:
        """Resolve spec sources in package -> global -> guides priority order."""
        if not spec_root.exists():
            return []

        requested_layers = self._requested_layers(task_type)
        sources: list[ContextSource] = []

        if package:
            package_root = spec_root / package
            if package_root.exists():
                package_sources = self._package_sources(package_root, package, requested_layers)
                sources.extend(package_sources)

        for layer in requested_layers:
            global_dir = spec_root / layer.value
            if global_dir.exists():
                sources.append(
                    self._make_spec_source(
                        global_dir,
                        identifier=layer.value,
                        layer=layer,
                        package=None,
                        package_specific=False,
                    )
                )

        guides_dir = spec_root / SpecLayer.GUIDES.value
        if guides_dir.exists():
            sources.append(
                self._make_spec_source(
                    guides_dir,
                    identifier=SpecLayer.GUIDES.value,
                    layer=SpecLayer.GUIDES,
                    package=None,
                    package_specific=False,
                )
            )

        deduplicated: list[ContextSource] = []
        seen_paths: set[str] = set()
        for source in sources:
            if not source.path:
                continue
            resolved = str(Path(source.path).resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            deduplicated.append(source)
        return deduplicated

    async def compile_layered_sources(
        self,
        *,
        sources: list[ContextSource],
        max_tokens: int | None = None,
        priority: list[str] | None = None,
        use_cache: bool = True,
    ) -> CompiledContext:
        """Compile sources with a per-source budget derived from layer priority."""
        budget = max_tokens or self.token_budget
        if not sources:
            return CompiledContext(
                sections=[],
                total_tokens=0,
                max_tokens=budget,
                sources=[],
            )

        combined_sections: list[ContextSection] = []
        dropped: list[str] = []
        deduplicated: list[str] = []
        source_ids: list[str] = []
        remaining_budget = budget

        grouped_sources = [
            [source for source in sources if bool(source.metadata.get("package_specific", False))],
            [source for source in sources if not bool(source.metadata.get("package_specific", False))],
        ]

        for group in grouped_sources:
            if not group or remaining_budget <= 0:
                continue
            group_remaining = remaining_budget
            for index, source in enumerate(group):
                if group_remaining <= 0:
                    break
                source_id = source.identifier or source.path or source.task_id or source.type
                source_ids.append(str(source_id))
                remaining_group = group[index:]
                allocation = self._allocate_source_budgets(remaining_group, group_remaining)[
                    str(source_id)
                ]
                if allocation <= 0:
                    continue
                compiled = await self.compile_sources(
                    sources=[source],
                    optimize=True,
                    max_tokens=max(1, allocation),
                    priority=priority or ["spec"],
                    use_cache=use_cache,
                )
                combined_sections.extend(compiled.sections)
                dropped.extend(compiled.dropped)
                deduplicated.extend(compiled.deduplicated)
                group_remaining = max(0, group_remaining - compiled.total_tokens)
            remaining_budget = group_remaining

        base_context = CompiledContext(
            sections=combined_sections,
            total_tokens=sum(section.token_count for section in combined_sections),
            max_tokens=budget,
            sources=source_ids,
            dropped=dropped,
            deduplicated=deduplicated,
            optimized=True,
        )

        if base_context.total_tokens <= budget:
            return base_context

        optimized = self._optimizer.optimize(
            base_context.sections,
            max_tokens=budget,
            priority=priority or ["spec"],
        )
        return replace(
            base_context,
            sections=optimized.sections,
            total_tokens=optimized.total_tokens,
            dropped=optimized.dropped,
            deduplicated=optimized.deduplicated,
        )

    # ------------------------------------------------------------------
    # Legacy Tier A: Standing law
    # ------------------------------------------------------------------
    def load_standing_law(self, repo_root: Path) -> list[ContextShard]:
        shards: list[ContextShard] = []
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            path = repo_root / name
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                shards.append(
                    ContextShard(
                        tier="A",
                        source=name,
                        content=text,
                        token_estimate=_estimate_tokens(text),
                        priority=100.0,
                    )
                )
        self._standing_law = shards
        return shards

    # ------------------------------------------------------------------
    # Legacy Tier B: Active working set
    # ------------------------------------------------------------------
    def build_active_set(
        self,
        run_id: str,
        snapshot: dict[str, Any],
        open_nodes: list[dict[str, Any]],
        eval_failures: list[dict[str, Any]],
        affected_files: list[str],
    ) -> list[ContextShard]:
        shards: list[ContextShard] = []

        snap_text = f"Run: {run_id}\nStatus: {snapshot.get('run_phase', '?')}"
        if snapshot.get("pending_approvals"):
            snap_text += f"\nPending approvals: {snapshot['pending_approvals']}"
        if snapshot.get("repairing_command_id"):
            snap_text += f"\nRepairing command: {snapshot['repairing_command_id']}"
        if snapshot.get("last_completed_repair"):
            repair = snapshot["last_completed_repair"]
            snap_text += (
                f"\nLast completed repair: {repair.get('failure_class', '?')} "
                f"via {repair.get('command_id', '?')}"
            )
        shards.append(
            ContextShard(
                tier="B",
                source="snapshot",
                content=snap_text,
                token_estimate=_estimate_tokens(snap_text),
                priority=90.0,
            )
        )

        for node in open_nodes[:5]:
            text = (
                f"Open node: {node.get('node_id', '?')} — {node.get('objective', '?')}"
            )
            shards.append(
                ContextShard(
                    tier="B",
                    source=f"open_node:{node.get('node_id')}",
                    content=text,
                    token_estimate=_estimate_tokens(text),
                    priority=85.0,
                )
            )

        for fail in eval_failures[:3]:
            text = f"Eval failure [{fail.get('failure_class', '?')}]: {fail.get('details', '')}"
            if fail.get("repair_route"):
                text += f"\nRepair route: {fail['repair_route']}"
            if "retry_allowed" in fail:
                text += f"\nRetry allowed: {fail['retry_allowed']}"
            if fail.get("repair_hints"):
                text += f"\nRepair hints: {', '.join(fail['repair_hints'])}"
            shards.append(
                ContextShard(
                    tier="B",
                    source="eval_failure",
                    content=text,
                    token_estimate=_estimate_tokens(text),
                    priority=88.0,
                )
            )

        if affected_files:
            text = "Affected files:\n" + "\n".join(
                f"  {path}" for path in affected_files[:20]
            )
            shards.append(
                ContextShard(
                    tier="B",
                    source="affected_files",
                    content=text,
                    token_estimate=_estimate_tokens(text),
                    priority=80.0,
                )
            )

        return shards

    # ------------------------------------------------------------------
    # Legacy Tier C: Folded memory
    # ------------------------------------------------------------------
    def add_folded(self, summaries: list[dict[str, Any]]) -> list[ContextShard]:
        shards: list[ContextShard] = []
        for summary in summaries:
            text = f"Episode {summary.get('episode_id', '?')}: {summary.get('outcome', '?')}"
            if summary.get("decisions"):
                text += f"\n  Decisions: {summary['decisions']}"
            if summary.get("invariants"):
                text += f"\n  Invariants: {summary['invariants']}"
            shards.append(
                ContextShard(
                    tier="C",
                    source=f"episode:{summary.get('episode_id')}",
                    content=text,
                    token_estimate=_estimate_tokens(text),
                    priority=50.0,
                )
            )
        self._folded = shards
        return shards

    # ------------------------------------------------------------------
    # Legacy Tier D: Cold retrieval
    # ------------------------------------------------------------------
    def add_cold(self, items: list[dict[str, Any]]) -> list[ContextShard]:
        shards: list[ContextShard] = []
        for item in items:
            text = str(item.get("content", ""))
            shards.append(
                ContextShard(
                    tier="D",
                    source=item.get("source", "cold"),
                    content=text,
                    token_estimate=_estimate_tokens(text),
                    priority=item.get("priority", 20.0),
                )
            )
        return shards

    # ------------------------------------------------------------------
    # Shared compile entrypoint: legacy sync or multi-source async
    # ------------------------------------------------------------------
    def compile(
        self,
        run_id: str | None = None,
        active_shards: list[ContextShard] | None = None,
        folded_shards: list[ContextShard] | None = None,
        cold_shards: list[ContextShard] | None = None,
        *,
        sources: list[ContextSource] | None = None,
        optimize: bool = False,
        max_tokens: int | None = None,
        priority: list[str] | None = None,
        use_cache: bool = True,
    ) -> WorkingSet | Awaitable[CompiledContext]:
        if sources is not None:
            return self.compile_sources(
                sources=sources,
                optimize=optimize,
                max_tokens=max_tokens,
                priority=priority,
                use_cache=use_cache,
            )

        if run_id is None or active_shards is None:
            raise ValueError("legacy compile requires run_id and active_shards")
        return self._compile_legacy(run_id, active_shards, folded_shards, cold_shards)

    def _compile_legacy(
        self,
        run_id: str,
        active_shards: list[ContextShard],
        folded_shards: list[ContextShard] | None = None,
        cold_shards: list[ContextShard] | None = None,
    ) -> WorkingSet:
        all_shards = list(self._standing_law) + list(active_shards)
        if folded_shards:
            all_shards.extend(folded_shards)
        if cold_shards:
            all_shards.extend(cold_shards)

        all_shards.sort(key=lambda shard: shard.priority, reverse=True)

        working_set = WorkingSet(run_id=run_id, budget=self.token_budget)
        for shard in all_shards:
            if working_set.total_tokens + shard.token_estimate <= self.token_budget:
                working_set.shards.append(shard)
                working_set.total_tokens += shard.token_estimate
            else:
                working_set.dropped.append(shard.source)
        return working_set

    # ------------------------------------------------------------------
    # Phase 6A: Multi-source compilation
    # ------------------------------------------------------------------
    async def compile_sources(
        self,
        *,
        sources: list[ContextSource],
        optimize: bool = True,
        max_tokens: int | None = None,
        priority: list[str] | None = None,
        use_cache: bool = True,
    ) -> CompiledContext:
        max_tokens = max_tokens or self.token_budget
        cache_key = self._build_cache_key(sources, optimize, max_tokens, priority)

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return replace(cached, cache_hit=True)

        sections: list[ContextSection] = []
        source_ids: list[str] = []
        for source in sources:
            source_id = source.identifier or source.path or source.task_id or source.type
            source_ids.append(str(source_id))
            sections.extend(await self._resolve_source(source))

        base_context = CompiledContext(
            sections=sections,
            total_tokens=sum(section.token_count for section in sections),
            max_tokens=max_tokens,
            sources=source_ids,
            cache_key=cache_key,
            optimized=False,
        )

        if optimize or base_context.total_tokens > max_tokens:
            optimized = self._optimizer.optimize(
                base_context.sections,
                max_tokens=max_tokens,
                priority=priority,
            )
            base_context = replace(
                base_context,
                sections=optimized.sections,
                total_tokens=optimized.total_tokens,
                dropped=optimized.dropped,
                deduplicated=optimized.deduplicated,
                optimized=True,
            )

        if use_cache:
            self._cache.set(cache_key, base_context)

        return base_context

    def _requested_layers(self, task_type: str) -> list[SpecLayer]:
        normalized = task_type.strip().lower()
        if normalized == "fullstack":
            return [SpecLayer.BACKEND, SpecLayer.FRONTEND]

        layer = SpecLayer.from_name(normalized)
        if layer != SpecLayer.CUSTOM and layer != SpecLayer.GUIDES:
            return [layer]

        if normalized == SpecLayer.GUIDES.value:
            return [SpecLayer.GUIDES]

        return [SpecLayer.BACKEND]

    def _package_sources(
        self,
        package_root: Path,
        package: str,
        requested_layers: list[SpecLayer],
    ) -> list[ContextSource]:
        sources: list[ContextSource] = []
        matched_standard_layer = False

        for layer in requested_layers:
            layer_dir = package_root / layer.value
            if not layer_dir.exists():
                continue
            matched_standard_layer = True
            sources.append(
                self._make_spec_source(
                    layer_dir,
                    identifier=f"package:{package}:{layer.value}",
                    layer=layer,
                    package=package,
                    package_specific=True,
                )
            )

        package_guides = package_root / SpecLayer.GUIDES.value
        if package_guides.exists():
            sources.append(
                self._make_spec_source(
                    package_guides,
                    identifier=f"package:{package}:{SpecLayer.GUIDES.value}",
                    layer=SpecLayer.GUIDES,
                    package=package,
                    package_specific=True,
                )
            )

        if matched_standard_layer:
            return sources

        if (package_root / "index.md").exists():
            sources.append(
                self._make_spec_source(
                    package_root,
                    identifier=f"package:{package}",
                    layer=SpecLayer.CUSTOM,
                    package=package,
                    package_specific=True,
                )
            )

        custom_children = sorted(
            child for child in package_root.iterdir() if child.is_dir() and not child.name.startswith(".")
        )
        if custom_children:
            for child in custom_children:
                layer = SpecLayer.from_name(child.name)
                sources.append(
                    self._make_spec_source(
                        child,
                        identifier=f"package:{package}:{child.name}",
                        layer=layer,
                        package=package,
                        package_specific=True,
                    )
                )
            return sources

        return sources

    def _make_spec_source(
        self,
        path: Path,
        *,
        identifier: str,
        layer: SpecLayer,
        package: str | None,
        package_specific: bool,
    ) -> ContextSource:
        weight = LAYER_PRIORITY[layer] * (1.5 if package_specific else 1.0)
        return ContextSource(
            type="spec",
            path=str(path.resolve()),
            identifier=identifier,
            priority=weight,
            metadata={
                "layer": layer.value,
                "package": package,
                "package_specific": package_specific,
                "token_weight": weight,
            },
        )

    def _allocate_source_budgets(
        self,
        sources: list[ContextSource],
        max_tokens: int,
    ) -> dict[str, int]:
        identifiers = [str(source.identifier or source.path or source.task_id or source.type) for source in sources]
        weights = [
            float(source.metadata.get("token_weight", source.priority or 1.0))
            for source in sources
        ]
        total_weight = sum(weights) or float(len(weights))
        minimum = 0 if max_tokens < len(sources) else max(1, max_tokens // max(1, len(sources) * 4))

        allocations: dict[str, int] = {}
        allocated = 0
        for identifier, weight in zip(identifiers, weights, strict=False):
            share = int(max_tokens * (weight / total_weight))
            budget = max(minimum, share)
            allocations[identifier] = budget
            allocated += budget

        while allocated > max_tokens and allocations:
            reduced = False
            for identifier in identifiers:
                if allocated <= max_tokens:
                    break
                if allocations[identifier] <= minimum:
                    continue
                allocations[identifier] -= 1
                allocated -= 1
                reduced = True
            if not reduced:  # pragma: no cover - defensive guard against invalid allocation state
                break

        while allocated < max_tokens and identifiers:
            for identifier in identifiers:
                if allocated >= max_tokens:
                    break
                allocations[identifier] += 1
                allocated += 1

        return allocations

    async def _resolve_source(self, source: ContextSource) -> list[ContextSection]:
        if source.type == "literal":
            identifier = source.identifier or "literal"
            content = source.content or ""
            return [
                ContextSection(
                    source_type=source.type,
                    identifier=identifier,
                    content=content,
                    token_count=_estimate_tokens(content),
                    priority=source.priority,
                    metadata=source.metadata,
                )
            ]

        if source.type == "spec":
            return self._load_spec_sections(source)

        if source.type == "task":
            return self._load_task_sections(source)

        if source.type == "journal":
            return await self._load_journal_sections(source)

        raise ValueError(f"unsupported context source type: {source.type}")

    def _load_spec_sections(self, source: ContextSource) -> list[ContextSection]:
        if not source.path:
            raise ValueError("spec context source requires path")
        root = Path(source.path)
        if not root.exists():
            return []

        paths = (
            [root]
            if root.is_file()
            else sorted(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".yaml", ".yml", ".json"}
            )
        )

        sections: list[ContextSection] = []
        for path in paths:
            content = path.read_text(encoding="utf-8", errors="replace")
            identifier = (
                source.identifier
                if root.is_file()
                else f"{source.identifier or root.name}:{path.relative_to(root).as_posix()}"
            )
            sections.append(
                ContextSection(
                    source_type="spec",
                    identifier=identifier or "unknown",
                    content=content,
                    token_count=_estimate_tokens(content),
                    priority=source.priority,
                    metadata={"path": path.as_posix(), **source.metadata},
                )
            )
        return sections

    def _load_task_sections(self, source: ContextSource) -> list[ContextSection]:
        if not source.task_id:
            raise ValueError("task context source requires task_id")
        if self._task_projection is None:
            raise ValueError("task projection is required for task context sources")

        task_context = self._task_projection.get_task_context(source.task_id)
        if task_context is None:
            return []

        metadata = task_context.metadata
        lines = [
            f"Task: {metadata.task_id}",
            f"Title: {metadata.title}",
            f"Type: {metadata.task_type}",
            f"Priority: {metadata.priority}",
            f"Status: {metadata.status.value}",
            f"Assignee: {metadata.assignee}",
            f"Branch: {metadata.branch} -> {metadata.base_branch}",
            "",
            "Acceptance criteria:",
        ]
        lines.extend(f"- {item}" for item in metadata.acceptance_criteria)
        lines.extend(
            [
                "",
                "PRD:",
                metadata.prd_content,
            ]
        )
        if task_context.events:
            lines.extend(
                [
                    "",
                    f"Task events recorded: {len(task_context.events)}",
                    "Latest task update:",
                    json.dumps(task_context.events[-1], sort_keys=True),
                ]
            )

        content = "\n".join(lines)
        return [
            ContextSection(
                source_type="task",
                identifier=source.identifier or metadata.task_id,
                content=content,
                token_count=_estimate_tokens(content),
                priority=source.priority + 10.0,
                metadata={"task_id": metadata.task_id, **source.metadata},
            )
        ]

    async def _load_journal_sections(self, source: ContextSource) -> list[ContextSection]:
        if self._journal is None:
            raise ValueError("journal is required for journal context sources")

        from_time = _coerce_datetime(source.from_time)
        to_time = _coerce_datetime(source.to_time)
        limit = source.limit or int(source.metadata.get("limit", 25))
        patterns = source.event_types or ["*"]

        events = []
        async for event in self._iter_journal_events(source.run_id):
            if not any(fnmatch(event.type, pattern) for pattern in patterns):
                continue
            if from_time and event.ts < from_time:
                continue
            if to_time and event.ts > to_time:
                continue
            events.append(event)

        events.sort(key=lambda event: (event.ts, event.seq))
        if limit > 0:
            events = events[-limit:]

        sections: list[ContextSection] = []
        for index, event in enumerate(events):
            content = self._format_event(event)
            sections.append(
                ContextSection(
                    source_type="journal",
                    identifier=f"{event.run_id}:{event.seq}:{event.type}",
                    content=content,
                    token_count=_estimate_tokens(content),
                    priority=max(1.0, source.priority - (len(events) - index) * 0.01),
                    metadata={
                        "event_type": event.type,
                        "run_id": event.run_id,
                        "timestamp": event.ts.isoformat(),
                        **source.metadata,
                    },
                )
            )
        return sections

    async def _iter_journal_events(self, run_id: str | None = None):
        if self._journal is None:
            return

        if run_id is not None:
            async for event in self._journal.read_from(run_id):
                yield event
            return

        journal_path = self._journal.path
        is_directory = journal_path.is_dir() or (
            not journal_path.exists() and not journal_path.suffix
        )
        paths = sorted(journal_path.glob("*.jsonl")) if is_directory else [journal_path]

        for path in paths:
            if not path.exists():  # pragma: no cover - file can disappear between discovery and read
                continue
            async with aiofiles.open(path, "r", encoding="utf-8") as handle:
                async for line in handle:
                    if not line.strip():
                        continue
                    yield event_from_dict(json.loads(line))

    @staticmethod
    def _format_event(event: Any) -> str:
        payload = json.dumps(event.payload, sort_keys=True)
        return (
            f"Time: {event.ts.isoformat()}\n"
            f"Run: {event.run_id}\n"
            f"Seq: {event.seq}\n"
            f"Actor: {event.actor.value}\n"
            f"Type: {event.type}\n"
            f"Payload: {payload}"
        )

    @staticmethod
    def _build_cache_key(
        sources: list[ContextSource],
        optimize: bool,
        max_tokens: int,
        priority: list[str] | None,
    ) -> str:
        payload = {
            "sources": [
                {
                    "type": source.type,
                    "identifier": source.identifier,
                    "path": source.path,
                    "task_id": source.task_id,
                    "run_id": source.run_id,
                    "event_types": source.event_types,
                    "content": source.content,
                    "priority": source.priority,
                    "metadata": source.metadata,
                    "from_time": (
                        dt.isoformat()
                        if (dt := _coerce_datetime(source.from_time))
                        else None
                    ),
                    "to_time": (
                        dt.isoformat()
                        if (dt := _coerce_datetime(source.to_time))
                        else None
                    ),
                    "limit": source.limit,
                }
                for source in sources
            ],
            "optimize": optimize,
            "max_tokens": max_tokens,
            "priority": priority or [],
        }
        return sha256(canonical_json(payload).encode("utf-8")).hexdigest()
