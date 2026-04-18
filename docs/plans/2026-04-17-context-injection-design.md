# Context Injection System - Reins Native Design

**Date:** 2026-04-17  
**Status:** Design Complete, Ready for Implementation  
**Goal:** Absorb trellis's context injection patterns as native Reins capabilities

---

## C. End-to-End Sequence

```
┌─────────────────────────────────────────────────────────────────────┐
│ AUTHORING PHASE                                                     │
└─────────────────────────────────────────────────────────────────────┘

Human writes spec
    ↓
.reins/spec/backend/error-handling.yaml
    ↓
SpecRegistrar.import_from_directory()
    ├→ Parse YAML manifest
    ├→ Validate structure
    ├→ Trust check (only system/admin)
    └→ Emit SpecRegisteredEvent
        ↓
EventJournal.append()

┌─────────────────────────────────────────────────────────────────────┐
│ PROJECTION BUILD PHASE                                              │
└─────────────────────────────────────────────────────────────────────┘

ContextSpecProjection.apply_event()
    ├→ Create SpecDescriptor
    ├→ Update primary index (specs dict)
    └→ Update secondary indexes
        ├→ by_scope
        ├→ by_task_type
        ├→ by_run_phase
        ├→ by_capability
        └→ by_visibility_tier

┌─────────────────────────────────────────────────────────────────────┐
│ SESSION BOOTSTRAP                                                   │
└─────────────────────────────────────────────────────────────────────┘

Orchestrator.bootstrap_session()
    ↓
Load current snapshot
    ├→ active_task: TaskState | None
    ├→ granted_capabilities: set[str]
    └→ open_decisions: list[Decision]
    ↓
ContextCompiler.seed_context(task_state, granted_capabilities, token_budget)
    ↓
ContextSpecProjection.resolve(SpecQuery)
    ├→ Scope filtering (workspace + task if applicable)
    ├→ Lifecycle filtering (exclude superseded/deactivated)
    ├→ Applicability matching (task_type, run_phase, actor_type, path)
    ├→ Capability filtering (required_capabilities ⊆ granted_capabilities)
    ├→ Visibility filtering (visibility_tier <= query.visibility_tier)
    └→ Precedence sorting (higher precedence first)
    ↓
Returns: list[ResolvedSpec]
    ↓
ContextCompiler._allocate_tokens()
    ├→ Separate by spec_type (standing_law, task_contract, spec_shard)
    ├→ Allocate token budget per type
    └→ Truncate if necessary
    ↓
Returns: ContextAssemblyManifest
    ├→ standing_law: list[SpecSection]
    ├→ task_contract: list[SpecSection]
    ├→ spec_shards: []  (empty at seed time)
    └→ total_tokens, token_breakdown, audit trail
    ↓
Agent session created with seed context

┌─────────────────────────────────────────────────────────────────────┐
│ PER-TURN ENRICHMENT                                                 │
└─────────────────────────────────────────────────────────────────────┘

Agent executes node in workflow
    ↓
Orchestrator detects run_phase change (e.g., "implement" → "check")
    ↓
ContextRecompositionManager.on_run_phase_change(new_phase, actor_type, path)
    ↓
ContextCompiler.enrich_context(base_manifest, run_phase, actor_type, path, ...)
    ↓
ContextSpecProjection.resolve(SpecQuery with run_phase, actor_type, path)
    ↓
Returns: list[ResolvedSpec] (spec_shards relevant to this phase)
    ↓
ContextCompiler._allocate_tokens() for spec_shards
    ↓
Merge with base_manifest
    ↓
Returns: Updated ContextAssemblyManifest
    ├→ standing_law: (unchanged from seed)
    ├→ task_contract: (unchanged from seed)
    ├→ spec_shards: list[SpecSection]  (newly added)
    └→ updated total_tokens, token_breakdown
    ↓
Agent sees enriched context for this turn

┌─────────────────────────────────────────────────────────────────────┐
│ RE-COMPOSITION TRIGGERS                                             │
└─────────────────────────────────────────────────────────────────────┘

Task switch → Re-run seed_context() with new task_state
Skill activation → Re-run resolve() with new granted_capabilities
Subagent spawn → Re-run enrich_context() with new actor_type
Hydrate → Restore manifest from checkpoint (no re-composition)
Retry → Re-run enrich_context() with new path/hypothesis
```

---

## D. Critical Review

### 1. Risk: Spec system evolving into a second skill system

**Assessment:** LOW RISK with clear boundaries

**Distinction:**

- **Skills** = executable capability modules with code, tools, and approval profiles
- **Specs** = passive documentation/guidance injected as context

**Boundaries enforced:**

- Specs have no execution logic, only content
- Specs cannot grant capabilities (policy engine does that)
- Specs cannot invoke tools or adapters
- Skills reference specs, but specs don't reference skills

**Mitigation:**

- Keep spec manifest schema minimal (no `execute`, `tools`, `adapters` fields)
- Document the distinction clearly in architecture docs

---

### 2. Risk: Policy/filtering confused with grants

**Assessment:** MEDIUM RISK, requires careful implementation

**Current design:**

- ContextSpecProjection filters specs by `required_capabilities`
- This is **visibility filtering**, not authorization
- A spec requiring `fs:write` won't be shown to an agent without that capability
- But showing a spec does NOT grant the capability

**Potential confusion:**

- Developer might think "if spec is visible, capability is granted"
- Agent might assume "I see error-handling spec, so I can write files"

**Mitigation:**

- Clear naming: `required_capabilities` → `visibility_requires_capabilities`
- Documentation: "Specs describe what you CAN do if granted, not what you ARE granted"
- Policy engine remains sole source of truth for grants
- Audit trail tracks: specs resolved vs capabilities granted (separate fields)

---

### 3. Risk: Breaking "cheap operations stay cheap"

**Assessment:** LOW RISK with projection design

**Hot paths:**

- `resolve()` queries in-memory indexes, no journal scan ✓
- Token counting happens once per spec at registration ✓
- Manifest assembly is O(n) where n = matching specs (typically <20) ✓

**Cold paths:**

- Projection rebuild from journal (only on startup or recovery)
- Spec registration (infrequent, admin-only operation)

**Potential issues:**

- Per-turn enrichment on every node execution
- If workflow has 100 nodes, that's 100 resolve() calls

**Mitigation:**

- Cache manifests per (run_phase, actor_type, path) tuple
- Invalidate cache only on capability grant change or task switch
- V1: No caching, measure performance first

---

### 4. Risk: Journal becoming a prompting source

**Assessment:** ZERO RISK, design prevents this

**Guarantees:**

- Agent never sees journal events directly
- Agent sees only ContextAssemblyManifest (compiled output)
- Manifest content comes from projection, not journal
- Journal is append-only audit trail, not query source

**Enforcement:**

- No `journal.query()` method exposed to compiler
- Projection is the only consumer of journal events
- Agent interface accepts only `ContextAssemblyManifest`, not events

---

### 5. Risk: Context drift after hydrate/retry

**Assessment:** MEDIUM RISK, requires careful trigger design

**Scenarios:**

**Hydrate (safe):**

- Checkpoint includes `ContextAssemblyManifest`
- On hydrate, restore manifest exactly as-is
- No re-composition, no drift

**Retry (potential drift):**

- Retry may change query params (new path, new hypothesis)
- Re-composition produces different manifest
- Agent sees different context than original attempt

**Is this drift acceptable?**

- YES for retry: new attempt should see updated context
- NO for hydrate: suspended run should resume with identical context

**Mitigation:**

- Checkpoint stores full `ContextAssemblyManifest`, not just query params
- Hydrate restores manifest, doesn't recompute
- Retry explicitly recomputes with new params
- Audit trail tracks: original_manifest_id vs retry_manifest_id

---

### 6. Risk: Precedence rules not deterministic

**Assessment:** LOW RISK with current design

**Determinism guarantees:**

- Precedence is explicit integer field in spec manifest
- Sorting by precedence is deterministic (stable sort)
- If two specs have same precedence, sort by spec_id (lexicographic)

**Potential issues:**

- Human error: two specs with same precedence and overlapping topics
- No conflict detection in v1

**Mitigation:**

- V1: Return all matching specs, let agent handle conflicts
- V2: Add conflict detection (detect overlapping topics via tags)
- V2: Add precedence validation (warn if two specs have same precedence)

---

### 7. Risk: Design breaks audit/replay/checkpoint/dehydration

**Assessment:** LOW RISK, design supports all

**Audit:**

- Every spec registration is an event in journal ✓
- Every manifest assembly includes audit trail (resolved_spec_ids, query_params) ✓
- Can reconstruct "what context did agent see" from manifest_id ✓

**Replay:**

- Projection rebuilds from journal events ✓
- Manifest assembly is deterministic given same query params ✓
- Can replay session and verify same specs were resolved ✓

**Checkpoint:**

- Checkpoint includes full `ContextAssemblyManifest` ✓
- Manifest is serializable (dataclass with primitives) ✓
- No references to live objects (projection, compiler) ✓

**Dehydration:**

- Manifest can be serialized to JSON ✓
- On hydrate, deserialize and restore ✓
- No re-composition needed ✓

---

## E. V1 Implementation Plan

### Phase 1: Foundation (Week 1)

**Components:**

1. Event types (`SpecRegisteredEvent`, `SpecSupersededEvent`, `SpecDeactivatedEvent`)
2. `SpecRegistrar` (directory import only, no API)
3. Basic projection (`ContextSpecProjection` with primary index only)

**Deliverables:**

- Can import specs from `.reins/spec/`
- Events written to journal
- Projection builds from events
- Tests: registrar validation, event emission, projection build

**Deferred:**

- Secondary indexes (use linear scan in v1)
- API registration
- Supersede/deactivate (register new specs only)

---

### Phase 2: Resolution (Week 2)

**Components:**

1. `SpecQuery` dataclass
2. `ContextSpecProjection.resolve()` (scope + lifecycle filtering only)
3. `ResolvedSpec` dataclass

**Deliverables:**

- Can query specs by scope
- Lifecycle filtering works (exclude superseded/deactivated)
- Tests: resolve by scope, lifecycle filtering

**Deferred:**

- Applicability matching (task_type, run_phase, actor_type, path)
- Capability filtering
- Visibility filtering

---

### Phase 3: Compilation (Week 3)

**Components:**

1. `ContextCompiler` (seed_context only)
2. `TokenBudget` and token allocation
3. `ContextAssemblyManifest`

**Deliverables:**

- Can assemble seed context from resolved specs
- Token budget allocation works
- Manifest includes audit trail
- Tests: seed context assembly, token allocation, truncation

**Deferred:**

- Per-turn enrichment (enrich_context)
- Fast/deliberative path distinction
- Folded memory

---

### Phase 4: Integration (Week 4)

**Components:**

1. `ContextRecompositionManager`
2. Integration with `Orchestrator.bootstrap_session()`
3. Checkpoint/hydrate support

**Deliverables:**

- Session bootstrap loads seed context
- Context included in agent session
- Checkpoint stores manifest
- Hydrate restores manifest
- Tests: end-to-end session bootstrap, checkpoint/hydrate

**Deferred:**

- Per-turn enrichment triggers
- Subagent context inheritance
- Skill activation triggers

---

## F. Open Questions for Implementation

1. **Token counting**: Use tiktoken? Custom counter? Approximate (chars/4)?
2. **Spec manifest format**: YAML or JSON? Both supported?
3. **Projection persistence**: Rebuild on every startup or cache to disk?
4. **Manifest storage**: Store in checkpoint or reconstruct on hydrate?
5. **Conflict resolution**: V2 feature or needed in v1?
6. **Path pattern matching**: Use fnmatch, glob, or regex?
7. **Folded memory**: Separate component or part of compiler?

---

## G. Success Criteria

**V1 is successful if:**

1. Specs can be authored in `.reins/spec/` and imported via registrar
2. Specs are stored as events in journal (immutable, auditable)
3. Projection builds queryable index from events
4. Compiler assembles seed context with token budget
5. Orchestrator loads seed context at session bootstrap
6. Agent sees project conventions without external hooks
7. Checkpoint/hydrate preserves context exactly
8. All operations are deterministic and auditable

**V1 does NOT need:**

- Per-turn enrichment (defer to v2)
- Applicability matching (defer to v2)
- Capability filtering (defer to v2)
- Conflict resolution (defer to v2)
- API registration (defer to v2)
- Supersede/deactivate (defer to v2)

---

## H. Migration from Trellis

**Current state:**

- `.trellis/spec/` exists with backend/frontend/guides
- `.trellis/workflow.md` describes trellis workflow
- `.trellis/scripts/` has task management

**Migration path:**

1. **Keep `.trellis/` for now** - Don't break existing workflow
2. **Add `.reins/spec/`** - New spec authoring location
3. **Import trellis specs** - Run registrar on `.trellis/spec/` to populate journal
4. **Parallel operation** - Both systems work during transition
5. **Deprecate trellis hooks** - Once Reins context injection is stable
6. **Remove `.trellis/`** - Final cleanup after full migration

**Timeline:** 2-3 months for full migration

---

## I. Next Steps

1. Review this design with team
2. Create implementation tasks in `.trellis/tasks/`
3. Start Phase 1 implementation (SpecRegistrar + events)
4. Write integration tests for end-to-end flow
5. Document spec authoring guide for developers
