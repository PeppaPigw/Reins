"""Context compiler — builds a token-budgeted working set for the model.

Implements the four-tier context stack from SystemDesign §7:

  Tier A: Standing law   (AGENTS.md, repo law, org policy tags, task contract)
  Tier B: Active working set (open nodes, affected files, diffs, eval failures)
  Tier C: Folded memory  (closed node summaries, key decisions, invariants)
  Tier D: Cold retrieval  (journal slices, old artifacts, prior runs)

The compiler assembles Tier A always, Tier B always, Tier C on demand,
Tier D only when explicitly requested.  It respects a token budget and
never injects raw journal history into the model context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContextShard:
    """One slice of compiled context."""

    tier: str  # "A", "B", "C", "D"
    source: str  # e.g. "agents.md", "open_task", "episode_summary"
    content: str
    token_estimate: int
    priority: float  # higher = more important, keep first under budget


@dataclass
class WorkingSet:
    """A fully compiled, budget-respecting context payload for one model turn."""

    run_id: str
    shards: list[ContextShard] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    dropped: list[str] = field(default_factory=list)


def _estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token estimate. Good enough for budgeting."""
    return max(1, len(text) // 4)


class ContextCompiler:
    """Assembles a token-budgeted working set for the model.

    Does NOT inject raw transcript or full journal.
    Produces compiled shards from durable state sources.
    """

    def __init__(self, token_budget: int = 120_000) -> None:
        self.token_budget = token_budget
        self._standing_law: list[ContextShard] = []
        self._folded: list[ContextShard] = []

    # ------------------------------------------------------------------
    # Tier A: Standing law — always loaded, highest priority
    # ------------------------------------------------------------------
    def load_standing_law(self, repo_root: Path) -> list[ContextShard]:
        """Scan repo for AGENTS.md / CLAUDE.md / GEMINI.md and load."""
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
    # Tier B: Active working set — current task state
    # ------------------------------------------------------------------
    def build_active_set(
        self,
        run_id: str,
        snapshot: dict[str, Any],
        open_nodes: list[dict[str, Any]],
        eval_failures: list[dict[str, Any]],
        affected_files: list[str],
    ) -> list[ContextShard]:
        """Build active working set shards from live state."""
        shards: list[ContextShard] = []

        # Current snapshot summary
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

        # Open task nodes
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

        # Eval failures (most recent N)
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

        # Affected files (just paths)
        if affected_files:
            text = "Affected files:\n" + "\n".join(
                f"  {f}" for f in affected_files[:20]
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
    # Tier C: Folded memory — closed episodes, decisions, invariants
    # ------------------------------------------------------------------
    def add_folded(self, summaries: list[dict[str, Any]]) -> list[ContextShard]:
        shards: list[ContextShard] = []
        for s in summaries:
            text = f"Episode {s.get('episode_id', '?')}: {s.get('outcome', '?')}"
            if s.get("decisions"):
                text += f"\n  Decisions: {s['decisions']}"
            if s.get("invariants"):
                text += f"\n  Invariants: {s['invariants']}"
            shard = ContextShard(
                tier="C",
                source=f"episode:{s.get('episode_id')}",
                content=text,
                token_estimate=_estimate_tokens(text),
                priority=50.0,
            )
            shards.append(shard)
        self._folded = shards
        return shards

    # ------------------------------------------------------------------
    # Tier D: Cold retrieval — journal slices, old artifacts
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
    # Assembly: merge all tiers under budget
    # ------------------------------------------------------------------
    def compile(
        self,
        run_id: str,
        active_shards: list[ContextShard],
        folded_shards: list[ContextShard] | None = None,
        cold_shards: list[ContextShard] | None = None,
    ) -> WorkingSet:
        """Merge shards under token budget, dropping lowest priority first."""
        all_shards = list(self._standing_law) + list(active_shards)
        if folded_shards:
            all_shards.extend(folded_shards)
        if cold_shards:
            all_shards.extend(cold_shards)

        all_shards.sort(key=lambda s: s.priority, reverse=True)

        ws = WorkingSet(run_id=run_id, budget=self.token_budget)
        for shard in all_shards:
            if ws.total_tokens + shard.token_estimate <= self.token_budget:
                ws.shards.append(shard)
                ws.total_tokens += shard.token_estimate
            else:
                ws.dropped.append(shard.source)
        return ws
