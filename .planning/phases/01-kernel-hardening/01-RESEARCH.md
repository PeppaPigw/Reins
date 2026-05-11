# Phase 1: Kernel Hardening - Research

**Researched:** 2026-05-11
**Domain:** Event-sourced kernel correctness, schema evolution, snapshot integrity
**Confidence:** HIGH

## Summary

Phase 1 hardens the event-sourced kernel to be provably correct, forward-compatible, and self-healing. The kernel currently has a functional but fragile foundation: events have a `schema_version: int = 1` field but no upcasting pipeline, snapshots are loaded without integrity validation, the reducer has no property-based test coverage, no `reins_version` is embedded in persisted artifacts, there are duplicate orchestrator/subagent implementations, and the journal is append-only with no compaction.

The codebase is well-structured with clear separation of concerns. The kernel layer (`src/reins/kernel/`) is pure domain with no I/O in reducers. The `EventEnvelope` is a frozen dataclass with SHA-256 checksum. The `EventJournal` uses JSONL files with fsync for durability. The `SnapshotStore` uses atomic JSON writes. These are solid foundations to build hardening on top of.

**Primary recommendation:** Implement the six KERN requirements in dependency order: version embedding (KERN-04) first (touches all persistence points), then schema versioning (KERN-01), snapshot integrity (KERN-02), duplicate consolidation (KERN-05), journal compaction (KERN-06), and property-based tests (KERN-03) last (validates everything else).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event schema versioning | Kernel (pure domain) | -- | Schema evolution is a kernel-internal concern; no I/O needed for upcasting |
| Snapshot integrity | Kernel (storage) | -- | Validation happens at load time in SnapshotStore |
| Reducer correctness | Kernel (pure domain) | -- | Reducers are pure functions; tests verify invariants |
| Version embedding | Kernel (storage) | All persistence layers | Every write path must embed version |
| Duplicate consolidation | Orchestration layer | Kernel layer | Merge orchestration/orchestrator.py into kernel/orchestrator.py |
| Journal compaction | Kernel (storage) | -- | Compaction is a journal-internal operation |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hypothesis | 6.152.5 | Property-based testing for reducer invariants | Industry standard for Python PBT; generates edge cases humans miss [VERIFIED: pip3 index] |
| pytest | >=8.0 | Test framework (already in dev deps) | Already used in project [VERIFIED: pyproject.toml] |
| pytest-asyncio | >=0.23 | Async test support (already in dev deps) | Already used in project [VERIFIED: pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib (stdlib) | -- | SHA-256 checksums for snapshot integrity | Already used for event checksums [VERIFIED: envelope.py] |
| dataclasses (stdlib) | -- | Frozen dataclass patterns | Already the project's data modeling approach [VERIFIED: codebase] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hypothesis | schemathesis | schemathesis is API-focused; hypothesis is better for pure function testing |
| Manual upcaster registry | pydantic model validators | Pydantic adds coupling; manual registry keeps kernel dependency-free |

**Installation:**
```bash
pip install "hypothesis>=6.100"
```

Add to `pyproject.toml` under `[project.optional-dependencies] dev`:
```toml
"hypothesis>=6.100",
```

## Architecture Patterns

### System Architecture Diagram

```
EventEnvelope (persisted JSONL)
    │
    ▼ read from journal
UpcasterRegistry.upcast(event, target_version)
    │
    ▼ upcasted event (in-memory only)
reduce(state, event) → RunState
    │
    ▼ periodic
SnapshotStore.save(state) → StateSnapshot (with integrity hash)
    │
    ▼ on load
SnapshotStore.load() → validate_integrity() → RunState
    │                         │ (if corrupt)
    │                         ▼
    │                   rebuild_from_journal()
    │
    ▼ on compaction trigger
EventJournal.compact(run_id, retention_policy) → compacted JSONL + snapshot
```

### Recommended Project Structure
```
src/reins/kernel/
├── event/
│   ├── envelope.py          # EventEnvelope (add reins_version field)
│   ├── journal.py           # EventJournal (add compaction)
│   ├── builder.py           # EventBuilder (unchanged)
│   ├── schema/              # NEW: schema versioning
│   │   ├── __init__.py
│   │   ├── registry.py      # UpcasterRegistry
│   │   └── upcasters/       # Per-event-type upcaster modules
│   │       └── __init__.py
│   └── compaction.py        # NEW: compaction logic
├── reducer/
│   ├── reducer.py           # reduce() (increment REDUCER_VERSION)
│   └── state.py             # RunState, StateSnapshot
├── snapshot/
│   ├── store.py             # SnapshotStore (add integrity validation)
│   └── integrity.py         # NEW: checksum computation + validation
├── orchestrator.py          # RunOrchestrator (canonical)
└── types.py                 # Kernel types
```

### Pattern 1: Upcaster Registry (KERN-01)

**What:** A chain of versioned transformers that convert event payloads from older schema versions to the current version at read time. Events are never mutated on disk.

**When to use:** Every time an event is deserialized from the journal.

**Example:**
```python
# Source: Event sourcing best practices [ASSUMED]
from typing import Callable

EventPayload = dict[str, Any]
Upcaster = Callable[[EventPayload], EventPayload]

class UpcasterRegistry:
    """Registry of event payload transformers keyed by (event_type, from_version)."""

    def __init__(self) -> None:
        self._upcasters: dict[tuple[str, int], Upcaster] = {}

    def register(self, event_type: str, from_version: int, upcaster: Upcaster) -> None:
        self._upcasters[(event_type, from_version)] = upcaster

    def upcast(self, event_type: str, payload: EventPayload, from_version: int, to_version: int) -> EventPayload:
        """Apply upcasters sequentially: v1 -> v2 -> v3 -> ... -> to_version."""
        current = payload
        for v in range(from_version, to_version):
            key = (event_type, v)
            if key in self._upcasters:
                current = self._upcasters[key](current)
            # If no upcaster registered, payload passes through unchanged
        return current
```

### Pattern 2: Snapshot Integrity Validation (KERN-02)

**What:** Compute a content hash over the snapshot's state fields at save time, store it alongside the snapshot. On load, recompute and compare. If mismatch, rebuild from journal.

**When to use:** Every snapshot load operation.

**Example:**
```python
# Source: Derived from existing checksum pattern in envelope.py [VERIFIED: codebase]
import hashlib
from reins.serde import canonical_json

def compute_snapshot_hash(snapshot: StateSnapshot) -> str:
    """Compute integrity hash over snapshot content (excluding the hash field itself)."""
    content = canonical_json({
        "run_id": snapshot.run_id,
        "event_seq": snapshot.event_seq,
        "reducer_version": snapshot.reducer_version,
        "run_phase": snapshot.run_phase,
        "active_grants": [vars(g) for g in snapshot.active_grants],
        "pending_approvals": snapshot.pending_approvals,
        # ... all state fields
    })
    return hashlib.sha256(content.encode()).hexdigest()
```

### Pattern 3: Property-Based Reducer Testing (KERN-03)

**What:** Use hypothesis to generate random sequences of valid events and verify reducer invariants hold regardless of input.

**When to use:** Continuous testing of reducer correctness.

**Example:**
```python
# Source: hypothesis documentation [ASSUMED]
from hypothesis import given, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule

class ReducerStateMachine(RuleBasedStateMachine):
    """Stateful property-based test for the reducer."""

    def __init__(self):
        super().__init__()
        self.state = RunState(run_id="test-run")
        self.events: list[EventEnvelope] = []

    @rule(event=valid_event_strategy())
    def apply_event(self, event):
        new_state = reduce(self.state, event)
        # Invariant: reducer never raises
        # Invariant: status transitions are valid
        assert new_state.status in VALID_TRANSITIONS.get(self.state.status, set()) | {self.state.status}
        self.state = new_state
        self.events.append(event)

    @rule()
    def replay_produces_same_state(self):
        """Replaying all events from scratch produces identical state."""
        replayed = RunState(run_id="test-run")
        for event in self.events:
            replayed = reduce(replayed, event)
        assert replayed == self.state
```

### Anti-Patterns to Avoid
- **Mutating stored events:** Never modify JSONL files. Upcasting happens in-memory at read time only.
- **Snapshot as source of truth:** Snapshots are an optimization. The journal is always authoritative. If they disagree, rebuild from journal.
- **Version checks in reducer logic:** The reducer should only see current-version payloads. Upcasting happens before the reducer sees the event.
- **Tight coupling between compaction and business logic:** Compaction is a storage concern. It should not change event semantics.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Property-based test generation | Custom random event generators | hypothesis strategies + stateful testing | Hypothesis handles shrinking, reproducibility, database of examples |
| JSON canonical form | Custom serializer | Existing `canonical_json()` from `serde.py` | Already handles dataclass/enum/datetime serialization [VERIFIED: serde.py] |
| Atomic file writes | Manual temp-file-and-rename | Existing `write_json_atomic()` from `serde.py` | Already handles fsync + atomic rename [VERIFIED: serde.py] |
| ULID generation | Custom ID generation | Existing `ulid` library | Already used throughout codebase [VERIFIED: pyproject.toml] |

**Key insight:** The codebase already has solid primitives for serialization, atomic writes, and ID generation. The hardening work builds on these rather than replacing them.

## Common Pitfalls

### Pitfall 1: Upcaster Ordering Bugs
**What goes wrong:** Upcasters applied in wrong order or skipped, producing corrupt state silently.
**Why it happens:** Version numbers get out of sync between the registry and persisted events.
**How to avoid:** Always iterate sequentially from `from_version` to `to_version`. Add an integration test that replays events from every historical version.
**Warning signs:** Tests that only use current-version events. No fixture files with old-format events.

### Pitfall 2: Snapshot Hash Covering Wrong Fields
**What goes wrong:** Adding a new field to StateSnapshot without updating the hash computation. Old snapshots validate correctly but are missing data.
**Why it happens:** Hash computation is separate from the dataclass definition.
**How to avoid:** Derive hash from `to_primitive(snapshot)` minus the hash field itself. This automatically includes new fields.
**Warning signs:** Snapshot loads succeed but state is subtly wrong.

### Pitfall 3: Compaction Losing Causation Chains
**What goes wrong:** Compaction removes intermediate events that other events reference via `causation_id` or `correlation_id`. Audit trail breaks.
**Why it happens:** Naive compaction (keep only last N events) doesn't understand event relationships.
**How to avoid:** Compaction must preserve the causal chain. Either keep all events referenced by `causation_id` from retained events, or compact into a summary event that preserves the chain metadata.
**Warning signs:** Time-travel debugging shows gaps. Correlation queries return incomplete results.

### Pitfall 4: Reducer Version Mismatch After Compaction
**What goes wrong:** A snapshot is taken with reducer v0.1.0, then the reducer is updated to v0.2.0 with different logic. Replaying from the old snapshot with the new reducer produces wrong state.
**Why it happens:** `reducer_version` in StateSnapshot is stored but never checked on load.
**How to avoid:** On snapshot load, compare `snapshot.reducer_version` with current `REDUCER_VERSION`. If they differ, invalidate the snapshot and rebuild from journal.
**Warning signs:** Different behavior for old runs vs new runs. Bugs that only appear when loading from snapshot.

### Pitfall 5: Consolidation Breaking Import Paths
**What goes wrong:** Merging duplicate implementations changes import paths, breaking all downstream code.
**Why it happens:** `from reins.orchestration.orchestrator import Orchestrator` is used in tests and other modules.
**How to avoid:** Keep the canonical path and add re-exports from the old path with deprecation warnings. Or do a clean break with a single commit that updates all imports.
**Warning signs:** ImportError in tests after consolidation.

## Code Examples

### Current EventEnvelope Structure (what we're extending)
```python
# Source: src/reins/kernel/event/envelope.py [VERIFIED: codebase]
@dataclass(frozen=True)
class EventEnvelope:
    run_id: str
    actor: Actor
    type: str
    payload: dict[str, Any]
    # ... other fields ...
    schema_version: int = 1  # <-- Currently global, not per-event-type
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    checksum: str = ""
```

### Current Reducer (what property tests will verify)
```python
# Source: src/reins/kernel/reducer/reducer.py [VERIFIED: codebase]
REDUCER_VERSION = "0.1.0"

def reduce(state: RunState, event: EventEnvelope) -> RunState:
    """Pure reducer. Returns new state from current state + event. No I/O."""
    # Handles 15 event types via if/elif chain
    # Returns replace(state, ...) for each case
    # Falls through to replace(state) for unknown events
```

### Current SnapshotStore (what we're adding integrity to)
```python
# Source: src/reins/kernel/snapshot/store.py [VERIFIED: codebase]
class SnapshotStore:
    async def save(self, snapshot: StateSnapshot) -> None:
        path = self.base_dir / snapshot.run_id / f"{snapshot.snapshot_id}.json"
        await write_json_atomic(path, to_primitive(snapshot))

    async def load(self, run_id: str, snapshot_id: str) -> StateSnapshot:
        path = self.base_dir / run_id / f"{snapshot_id}.json"
        return _snapshot_from_dict(await read_json(path))
        # <-- No integrity check currently
```

### Version Embedding Pattern (KERN-04)
```python
# Source: Design pattern for this project [ASSUMED]
from reins import __version__ as REINS_VERSION

# In EventBuilder.commit():
event = EventEnvelope(
    ...,
    payload={**payload, "_reins_version": REINS_VERSION},
    # OR: add reins_version as a top-level field on EventEnvelope
)

# In SnapshotStore.save():
data = to_primitive(snapshot)
data["_reins_version"] = REINS_VERSION
await write_json_atomic(path, data)
```

### Journal Compaction Pattern (KERN-06)
```python
# Source: Event sourcing compaction patterns [ASSUMED]
@dataclass
class RetentionPolicy:
    max_events: int = 10_000          # Compact when journal exceeds this
    keep_last_n: int = 1_000          # Always keep the most recent N events
    keep_after_snapshot: bool = True   # Keep events after last snapshot
    preserve_causation: bool = True   # Never break causation chains

async def compact(self, run_id: str, policy: RetentionPolicy) -> int:
    """Compact journal for a run. Returns number of events removed."""
    # 1. Take a snapshot at current state
    # 2. Identify events safe to remove (before snapshot, outside retention window)
    # 3. If preserve_causation: keep events referenced by retained events
    # 4. Rewrite journal file atomically (temp file + rename)
    # 5. Return count of removed events
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Global schema_version on envelope | Per-event-type versioning with upcaster chains | Standard since ~2020 in event sourcing | Enables independent evolution of different event types |
| Snapshot without validation | Content-addressed snapshots with integrity hash | Standard practice | Detects corruption, enables auto-rebuild |
| Manual reducer testing | Property-based testing with hypothesis | hypothesis 6.x (stable since 2022) | Finds edge cases humans miss; proves invariants |
| No version in artifacts | Embedded version in all persisted data | Standard for any upgradeable system | Enables migration tooling |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Per-event-type versioning is better than global schema_version | Architecture Patterns | Low - global versioning still works, just less granular |
| A2 | Compaction should preserve causation chains | Code Examples | Medium - if causation chains aren't used downstream, simpler compaction is fine |
| A3 | `reins_version` should go in payload rather than as a top-level envelope field | Code Examples | Low - either approach works; top-level is cleaner but requires envelope schema change |
| A4 | hypothesis stateful testing is the right approach for reducer | Pattern 3 | Low - even basic @given tests provide value |

## Open Questions (RESOLVED)

1. **Per-event-type vs global schema versioning** — RESOLVED: Global versioning (simpler). The upcaster registry supports both; start global, add per-type only if event types evolve at different rates.

2. **Where to embed reins_version: envelope field vs payload key** — RESOLVED: Top-level field on EventEnvelope. Cleaner, explicit, type-safe. One-time schema change accepted.

3. **Consolidation strategy for duplicates** — RESOLVED: Implementations are complementary, not duplicates. Consolidate by making `orchestration.Orchestrator` delegate to `kernel.RunOrchestrator`. Merge SubagentManagers into one supporting both worktree and logical isolation modes.

4. **Compaction trigger: automatic vs manual** — RESOLVED: Manual first (`reins compact` CLI) + configurable auto-trigger threshold for later.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KERN-01 | Event schema versioned types with upcaster registry | UpcasterRegistry pattern, per-event-type versioning design, integration with existing `event_from_dict()` |
| KERN-02 | Snapshot integrity validation + auto-rebuild | Content hash pattern using existing `canonical_json()`, rebuild via existing `RunOrchestrator.rebuild()` |
| KERN-03 | Reducer property-based tests | hypothesis 6.152.5 with stateful testing, invariants identified (replay correctness, valid transitions, purity) |
| KERN-04 | Embed reins_version in all persisted artifacts | Three persistence points identified: EventEnvelope, StateSnapshot, CheckpointManifest |
| KERN-05 | Consolidate duplicate implementations | Analysis complete: orchestration.Orchestrator wraps kernel.RunOrchestrator; two SubagentManagers serve different isolation modes |
| KERN-06 | Journal compaction with retention policy | RetentionPolicy design, causation-preserving compaction, atomic rewrite pattern |
</phase_requirements>

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ + hypothesis 6.152.5 |
| Config file | None (uses pyproject.toml defaults) |
| Quick run command | `python -m pytest tests/test_reducer.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KERN-01 | Upcaster converts v1 events to v2 correctly | unit | `pytest tests/test_upcaster_registry.py -x` | Wave 0 |
| KERN-01 | Full replay with mixed-version events produces correct state | integration | `pytest tests/test_schema_evolution.py -x` | Wave 0 |
| KERN-02 | Corrupt snapshot detected and rebuilt from journal | integration | `pytest tests/test_snapshot_integrity.py -x` | Wave 0 |
| KERN-03 | Reducer replay invariant holds for random event sequences | property | `pytest tests/test_reducer_properties.py -x` | Wave 0 |
| KERN-03 | Reducer is pure (no mutation of input state) | property | `pytest tests/test_reducer_properties.py::test_purity -x` | Wave 0 |
| KERN-04 | All persisted artifacts contain reins_version | unit | `pytest tests/test_version_embedding.py -x` | Wave 0 |
| KERN-05 | Consolidated orchestrator passes existing test suite | integration | `pytest tests/test_orchestrator.py -x` | Existing |
| KERN-06 | Compaction reduces journal size while preserving replay correctness | integration | `pytest tests/test_journal_compaction.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_reducer.py tests/test_reducer_properties.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_upcaster_registry.py` -- covers KERN-01
- [ ] `tests/test_schema_evolution.py` -- covers KERN-01 integration
- [ ] `tests/test_snapshot_integrity.py` -- covers KERN-02
- [ ] `tests/test_reducer_properties.py` -- covers KERN-03
- [ ] `tests/test_version_embedding.py` -- covers KERN-04
- [ ] `tests/test_journal_compaction.py` -- covers KERN-06
- [ ] Add `hypothesis>=6.100` to dev dependencies in pyproject.toml

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | Validate event payloads during upcasting; reject malformed snapshots |
| V6 Cryptography | yes | SHA-256 for integrity hashes (not security-critical, just tamper detection) |

### Known Threat Patterns for Event-Sourced Kernel

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Tampered journal file | Tampering | SHA-256 checksum per event (already implemented) |
| Corrupt snapshot injection | Tampering | Integrity hash validation on load (KERN-02) |
| Schema downgrade attack | Tampering | Reject events with schema_version > current known max |
| Journal file deletion | Denial of Service | Compaction preserves minimum events; snapshots enable partial recovery |

## Duplicate Implementation Analysis (KERN-05)

### Orchestrators

| Module | Class | Responsibility | Lines |
|--------|-------|---------------|-------|
| `src/reins/kernel/orchestrator.py` | `RunOrchestrator` | Full run lifecycle: intake, route, process_proposal, dehydrate/hydrate, task management | ~820 |
| `src/reins/orchestration/orchestrator.py` | `Orchestrator` | Intent routing, policy evaluation, subagent spawning, result collection | ~350 |

**Relationship:** `orchestration.Orchestrator` is a higher-level coordinator that routes intents and spawns subagents. `kernel.RunOrchestrator` is the per-run supervisor loop. They are complementary, not duplicates. However, `orchestration.Orchestrator` reimplements event emission and policy evaluation that `RunOrchestrator` already handles.

**Consolidation strategy:** Make `orchestration.Orchestrator` create and delegate to `RunOrchestrator` instances for each spawned subagent run, rather than reimplementing the event emission pattern.

### SubagentManagers

| Module | Class | Responsibility | Lines |
|--------|-------|---------------|-------|
| `src/reins/orchestration/subagent_manager.py` | `SubagentManager` | Worktree-based isolation, MCP sessions, context injection hooks, agent registry | ~500 |
| `src/reins/subagent/manager.py` | `SubagentManager` | Logical child runs with inherited grants, turn limits, token budgets, RunOrchestrator per child | ~355 |

**Relationship:** These serve different isolation modes. The orchestration version manages physical isolation (worktrees, MCP sessions). The subagent version manages logical isolation (child RunOrchestrators with scoped grants).

**Consolidation strategy:** Merge into a single `SubagentManager` with an `isolation_level` parameter that determines behavior:
- `IsolationLevel.NONE` / `IsolationLevel.LOGICAL` -> current `subagent.manager` behavior
- `IsolationLevel.WORKTREE` -> current `orchestration.subagent_manager` behavior

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `src/reins/kernel/event/envelope.py`, `journal.py`, `reducer/reducer.py`, `reducer/state.py`, `snapshot/store.py`, `orchestrator.py` [VERIFIED: direct file reads]
- Codebase analysis: `src/reins/orchestration/orchestrator.py`, `subagent_manager.py`, `src/reins/subagent/manager.py` [VERIFIED: direct file reads]
- pip3 index: hypothesis 6.152.5 latest [VERIFIED: pip3 index versions]
- pyproject.toml: existing dependencies and test infrastructure [VERIFIED: direct file read]

### Secondary (MEDIUM confidence)
- `.planning/research/PITFALLS.md` - Event schema ossification, snapshot invalidation patterns
- `.planning/research/ARCHITECTURE.md` - Kernel layer boundaries, data flow
- `.planning/codebase/ARCHITECTURE.md` - Current component responsibilities

### Tertiary (LOW confidence)
- Event sourcing upcaster patterns (training knowledge) [ASSUMED]
- Journal compaction best practices (training knowledge) [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - hypothesis verified on registry, existing deps confirmed in pyproject.toml
- Architecture: HIGH - based on direct codebase analysis of all relevant files
- Pitfalls: HIGH - derived from actual code patterns observed (e.g., no integrity check in SnapshotStore.load)
- Consolidation analysis: HIGH - both implementations read and compared in full

**Research date:** 2026-05-11
**Valid until:** 2026-06-11 (stable domain, no external API dependencies)
