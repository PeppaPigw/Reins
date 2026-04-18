# Trellis Integration Roadmap for Reins (REVISED)

**Goal:** Adopt Trellis's proven UX patterns as an **export/adapter layer** over Reins's event-sourced core.

**Status:** Planning phase - Architecture revised after Codex review

**Critical Insight:** Trellis patterns (`.reins/tasks/`, JSONL files, hooks) should be **derived artifacts** for platform interop, NOT canonical state. Journal/projections remain the source of truth.

---

## Architecture: Export Layer Over Event-Sourced Core

```
┌─────────────────────────────────────┐
│   Canonical State (Event-Sourced)  │
│  Journal → Projections → RunState   │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│      Export Layer (Derived)         │
│  .reins/tasks/ (task.json, JSONL)  │
│  .current-task (pointer file)       │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│    Hooks (Platform Adapter)         │
│  session-start.py, subagent-ctx.py  │
└─────────────────────────────────────┘
```

**Key Principles:**
1. Event journal is authoritative - all state derives from events
2. `.reins/tasks/` files are **exports** for platform interop, not primary storage
3. Hooks are **adapters** that read exports and inject into platform-specific contexts
4. Existing `RunOrchestrator.bootstrap_session()` remains the internal mechanism
5. Worktrees integrate with `SubagentManager`, not a parallel orchestration stack

---

## Revised Task Breakdown (15 Tasks)

### Phase 1: Canonical State Model (Week 1)

**Task 1.1: Platform Registry**
- Create `src/reins/platform/registry.py`
- Define PlatformConfig for Claude Code, Codex, Cursor
- Platform capability flags (supports_hooks, supports_agents)
- **Deliverable:** Single source of truth for platform metadata

**Task 1.2: Spec YAML Schema**
- Implement YAML manifest validation
- Schema: spec_type, scope, precedence, visibility_tier, applicability, content
- Leverage existing SpecRegistrar for import
- **Deliverable:** Validated YAML specs in `.reins/spec/`

**Task 1.3: Task Export Schema**
- Define export format for task.json (from TaskMetadata)
- Define JSONL format for agent context
- **NOT** a new storage layer - just export format
- **Deliverable:** Schema definitions, no implementation yet

**Task 1.4: Context Enrichment**
- Implement `ContextCompilerV2.enrich_context()`
- Trigger types: run_phase_change, capability_grant, task_switch
- Add spec_shards based on current phase/actor
- **Deliverable:** Dynamic context updates (missing from current code)

---

### Phase 2: Export Layer (Week 2)

**Task 2.1: Task Export Manager**
- Create `src/reins/export/task_exporter.py`
- Export TaskMetadata → `.reins/tasks/{id}/task.json`
- Export TaskContext → `.reins/tasks/{id}/prd.md`
- Export agent context → `.reins/tasks/{id}/{agent}.jsonl`
- **Source:** TaskContextProjection (read-only)
- **Deliverable:** Derived artifacts for platform interop

**Task 2.2: Current Task Pointer**
- Export `RunState.active_task_id` → `.reins/.current-task`
- Update on task activation/completion
- **Source:** RunOrchestrator state
- **Deliverable:** Pointer file for hooks

**Task 2.3: Spec Export Manager**
- Export ContextSpecProjection → `.reins/spec/` (if needed)
- Primarily for documentation/review, not runtime
- **Deliverable:** Human-readable spec exports

**Task 2.4: Export Sync Strategy**
- When to trigger exports (on event? on checkpoint? on demand?)
- Orphan cleanup (remove exports for archived tasks)
- **Deliverable:** Export lifecycle policy

---

### Phase 3: Platform Adapter Layer (Week 3)

**Task 3.1: Hook Contract**
- Define hook interface for Claude Code (single platform first)
- Input: `.current-task`, `.reins/tasks/`, `.reins/spec/`
- Output: Context string for injection
- **Deliverable:** Hook specification document

**Task 3.2: Session Start Hook**
- Implement `session-start.py` for Claude Code
- Read `.current-task` → load task.json, prd.md
- Query relevant specs from `.reins/spec/`
- Format for Claude Code context injection
- **Deliverable:** Working hook for session bootstrap

**Task 3.3: Subagent Context Hook**
- Implement `inject-subagent-context.py` for Claude Code
- Read agent-specific JSONL from `.reins/tasks/{id}/{agent}.jsonl`
- Inject before subagent spawn
- **Deliverable:** Working hook for subagent context

**Task 3.4: Hook Integration Test**
- Test hook execution timing
- Test context injection correctness
- Test missing file handling
- **Deliverable:** Hook test suite

---

### Phase 4: Worktree Integration (Week 4)

**Task 4.1: Worktree-Subagent Integration**
- Extend `SubagentManager.spawn()` to support worktree isolation
- Use existing `WorktreeManager` for worktree creation
- Copy `.reins/.developer` to worktree
- Set `.current-task` in worktree
- **Deliverable:** Subagents can spawn in isolated worktrees

**Task 4.2: Worktree Cleanup**
- Implement orphan detection and cleanup
- Merge strategy on completion
- **Deliverable:** Worktree lifecycle management

**Task 4.3: CLI Commands**
- `reins task create/start/finish/list` (uses TaskManager)
- `reins spec import/list` (uses SpecRegistrar)
- `reins export sync` (triggers export layer)
- **Deliverable:** User-facing CLI

---

### Phase 5: Hardening (Week 5-6)

**Task 5.1: Integration Tests**
- End-to-end: task creation → export → hook injection → subagent spawn
- Test worktree isolation
- Test export sync
- **Deliverable:** Full integration test suite

**Task 5.2: Migration System (Deferred)**
- Only implement after formats stabilize
- Declarative JSON manifests
- **Deliverable:** Migration framework (low priority)

---

## Dependency Graph

```
1.1 Platform Registry
  ↓
1.2 Spec YAML Schema ──→ 2.3 Spec Export
  ↓
1.3 Task Export Schema ──→ 2.1 Task Export Manager
  ↓                           ↓
1.4 Context Enrichment      2.2 Current Task Pointer
                              ↓
                            2.4 Export Sync Strategy
                              ↓
                            3.1 Hook Contract
                              ↓
                            3.2 Session Start Hook
                              ↓
                            3.3 Subagent Context Hook
                              ↓
                            3.4 Hook Integration Test
                              ↓
                            4.1 Worktree-Subagent Integration
                              ↓
                            4.2 Worktree Cleanup
                              ↓
                            4.3 CLI Commands
                              ↓
                            5.1 Integration Tests
```

---

## Source of Truth Rules

| Component | Canonical State | Derived Artifacts | Purpose of Derived |
|-----------|----------------|-------------------|-------------------|
| **Tasks** | TaskContextProjection (from events) | `.reins/tasks/{id}/task.json` | Platform interop, human review |
| **Task Context** | Event history in projection | `.reins/tasks/{id}/{agent}.jsonl` | Hook injection for agents |
| **Active Task** | `RunState.active_task_id` | `.reins/.current-task` | Hook pointer file |
| **Specs** | ContextSpecProjection (from events) | `.reins/spec/*.yaml` | Source files (imported via SpecRegistrar) |
| **Worktrees** | WorktreeManager state | Git worktree list | Git-managed isolation |

**Critical Rules:**
1. **Never read derived artifacts to update canonical state** - that creates circular dependencies
2. **Exports are one-way** - Projection → File, never File → Projection
3. **Hooks are read-only** - They consume exports but never write back
4. **Replay must work without exports** - Journal replay rebuilds all projections independently

---

## How Reins Exceeds Trellis

| Feature | Trellis | Reins |
|---------|---------|-------|
| **State Model** | File-based (`.trellis/tasks/`) | Event-sourced journal + projections |
| **Source of Truth** | Filesystem | Event journal (files are exports) |
| **Audit Trail** | Git history only | Immutable event stream |
| **Query Performance** | File scanning | In-memory projections |
| **Context Optimization** | No token management | Token budget allocation |
| **State Recovery** | Manual file repair | Replay from journal |
| **Crash Recovery** | Orphaned files | Checkpoint/restore |
| **Spec Metadata** | Markdown only | YAML with applicability rules |
| **Pipeline Observability** | Logs only | Event stream + projections |
| **Concurrency** | File locking | Event-sourced (no locks needed) |

---

## Implementation Timeline (Revised)

**Week 1: Canonical State Model**
- Day 1-2: Platform registry (1.1)
- Day 3-4: Spec YAML schema (1.2)
- Day 5: Task export schema (1.3)
- Day 6-7: Context enrichment (1.4)

**Week 2: Export Layer**
- Day 1-3: Task export manager (2.1)
- Day 4: Current task pointer (2.2)
- Day 5: Spec export manager (2.3)
- Day 6-7: Export sync strategy (2.4)

**Week 3: Platform Adapter**
- Day 1: Hook contract (3.1)
- Day 2-3: Session start hook (3.2)
- Day 4-5: Subagent context hook (3.3)
- Day 6-7: Hook integration test (3.4)

**Week 4: Worktree Integration**
- Day 1-3: Worktree-subagent integration (4.1)
- Day 4-5: Worktree cleanup (4.2)
- Day 6-7: CLI commands (4.3)

**Week 5-6: Hardening**
- Week 5: Integration tests (5.1)
- Week 6: Migration system (5.2, deferred if needed)

**Total: 5-6 weeks for complete implementation**

---

## Success Criteria

**Functional:**
- [ ] Specs automatically injected at session start via hooks
- [ ] Task context preserved and exported to JSONL
- [ ] Subagents spawn in isolated worktrees
- [ ] Hooks read exports correctly
- [ ] CLI provides task/spec management

**Architectural:**
- [ ] Event journal remains canonical - no dual source of truth
- [ ] Exports are derived artifacts only
- [ ] Replay works without exports (journal → projections)
- [ ] Hooks are adapters, not core architecture
- [ ] Worktrees integrate with SubagentManager, not parallel stack

**Quality:**
- [ ] Integration tests cover full workflow
- [ ] Orphan cleanup prevents resource leaks
- [ ] Token budgets prevent context overflow
- [ ] Crash recovery via checkpoint/restore

---

## Risk Mitigation

**Risk: Shadow state drift**
- Mitigation: Exports are one-way only, never read back into canonical state
- Validation: Integration tests verify replay without exports

**Risk: Hook timing differences across platforms**
- Mitigation: Start with single platform (Claude Code), generalize later
- Validation: Hook contract specifies timing guarantees

**Risk: Worktree orphans**
- Mitigation: Implement cleanup in WorktreeManager
- Validation: Test crash scenarios and cleanup

**Risk: Circular dependencies (File → Projection → File)**
- Mitigation: Strict rule - projections never read exports
- Validation: Code review + architecture tests

---

## Next Steps

1. ✅ Codex review completed - critical issues identified
2. ✅ Roadmap revised with export/adapter architecture
3. **Next:** Start Task 1.1 (Platform Registry)
4. Implement in dependency order
5. Integration test after each phase
6. Document patterns as we go

**Target:** 5-6 weeks for complete Trellis integration as export/adapter layer over event-sourced core.
