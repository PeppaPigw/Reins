# Roadmap: Reins

## Overview

Reins must surpass Trellis across all 14 engineering dimensions. This roadmap delivers that goal through 9 phases: hardening the event-sourced kernel, locking down security, achieving platform parity (3 to 14+), building workflow UX, packaging for release, instrumenting performance and observability, wiring integrations, polishing developer experience with documentation, and establishing the CI/quality gate infrastructure. Testing is interleaved throughout — each phase carries the test requirements that validate its deliverables.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Kernel Hardening** - Event schema versioning, snapshot integrity, reducer correctness, journal compaction
- [x] **Phase 2: Security & Policy** - Shell safety, network binding, policy enforcement, TLS validation, threat model, input validation
- [x] **Phase 3: Platform Parity** - Template engine, hash-based staleness detection, 14+ platform configurators with contract tests
- [ ] **Phase 4: Workflow UX & Skills** - Session breadcrumbs, brainstorm/planning skill, break-loop, spec updates, task pointer, state machine
- [ ] **Phase 5: Migration & Packaging** - Two-layer migrations, pip install, PyPI publishing, semver, CLI init/update/uninstall
- [ ] **Phase 6: Performance & Observability** - Thread pool offload, event loop monitoring, compilation speed, startup time, benchmarks, structured logging, tracing, time-travel
- [ ] **Phase 7: Integrations** - GitHub, Linear, Slack, issue-tracker-as-control-plane
- [ ] **Phase 8: Documentation & Developer Experience** - API reference, architecture guide, quick-start, platform guides, examples, migration guide, error messages, shell completion, doctor command
- [ ] **Phase 9: Testing Infrastructure & CI** - Unit coverage >90%, property-based tests, integration tests, CI matrix, historical replay fixtures

## Phase Details

### Phase 1: Kernel Hardening
**Goal**: The event-sourced kernel is provably correct, forward-compatible, and self-healing
**Depends on**: Nothing (first phase)
**Requirements**: KERN-01, KERN-02, KERN-03, KERN-04, KERN-05, KERN-06
**Success Criteria** (what must be TRUE):
  1. Events persisted with old schema versions replay correctly through upcasters without data loss
  2. Corrupted snapshots are detected on load and the system rebuilds state from the journal automatically
  3. Reducer functions satisfy commutativity and idempotency invariants under property-based testing
  4. Journal compaction reduces storage while preserving full replay capability within retention window
  5. A single canonical orchestration path exists with no duplicate implementations
**Plans:** 4 plans
Plans:
- [ ] 01-01-PLAN.md — Version embedding + event schema versioning with upcaster registry
- [ ] 01-02-PLAN.md — Snapshot integrity validation + journal compaction
- [ ] 01-03-PLAN.md — Orchestrator consolidation (eliminate duplicate implementations)
- [ ] 01-04-PLAN.md — Property-based reducer tests with hypothesis

### Phase 2: Security & Policy
**Goal**: All execution paths are sandboxed, validated, and formally threat-modeled
**Depends on**: Phase 1
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06
**Success Criteria** (what must be TRUE):
  1. Shell commands execute via exec-style invocation with no shell injection vectors
  2. API server refuses remote connections unless explicitly configured with a flag
  3. No code path can execute a capability-gated action without passing through the policy engine
  4. A published threat model covers sandboxing, exfiltration, and privilege escalation with mitigations
  5. Malformed CLI args, API payloads, and config files produce structured validation errors (not crashes)
**Plans:** 3 plans
Plans:
- [x] 02-01-PLAN.md — Shell exec hardening + API localhost binding (SEC-01, SEC-02)
- [x] 02-02-PLAN.md — TLS validation + policy bypass audit (SEC-03, SEC-04)
- [x] 02-03-PLAN.md — Input validation + formal threat model (SEC-05, SEC-06)

### Phase 3: Platform Parity
**Goal**: Reins generates valid, tested configurations for 14+ AI coding platforms
**Depends on**: Phase 1
**Requirements**: PLAT-01, PLAT-02, PLAT-03, PLAT-04, PLAT-05, PLAT-06, PLAT-07, TEST-04
**Success Criteria** (what must be TRUE):
  1. A single template engine produces platform configs from declarative descriptors (no per-platform code duplication)
  2. Running `reins update` detects stale configs via hash comparison and prompts the user
  3. Tier 1 platforms (Claude, Cursor, Codex) pass full integration test suites in CI
  4. All 14+ platforms produce configs that pass contract validation against their respective schemas
  5. Hook generation outputs the correct language (Python or JS) per platform convention
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — Declarative platform descriptors + template engine + reins update command (PLAT-01, PLAT-02)
- [x] 03-02-PLAN.md — Contract validation schemas + hook generation (PLAT-04, PLAT-05, PLAT-07)
- [x] 03-03-PLAN.md — Tier 1 integration tests + full contract test run (PLAT-03, PLAT-06, TEST-04)

### Phase 4: Workflow UX & Skills
**Goal**: Users experience guided, stateful workflows that capture and reuse knowledge
**Depends on**: Phase 3
**Requirements**: WF-01, WF-02, WF-03, WF-04, WF-05, WF-06
**Success Criteria** (what must be TRUE):
  1. Each agent turn receives a breadcrumb showing current workflow state and available transitions
  2. The brainstorm skill produces a structured PRD through guided questioning
  3. Break-loop triggers a retrospective that captures learnings into the knowledge base
  4. Task learnings flow back into the spec system via the spec-update workflow
  5. Workflow transitions follow a configurable state machine (planning -> in_progress -> checking -> done)
**Plans**: 3 plans
Plans:
- [x] 04-01-PLAN.md — Workflow state machine + breadcrumb injection (WF-01, WF-05)
- [x] 04-02-PLAN.md — Brainstorm skill + break-loop detection (WF-02, WF-03)
- [x] 04-03-PLAN.md — Retrospective capture + spec-update learning flow (WF-03, WF-04)

### Phase 5: Migration & Packaging
**Goal**: Users install Reins with a single pip command and upgrade without data loss
**Depends on**: Phase 4
**Requirements**: PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, PKG-06, PKG-07, TEST-03
**Success Criteria** (what must be TRUE):
  1. `pip install reins` produces a working CLI with all dependencies resolved
  2. `reins init` detects project type and generates appropriate platform configs interactively
  3. `reins update` migrates both user configs and internal state with rollback on failure
  4. `reins uninstall` removes all generated files cleanly
  5. PyPI releases happen automatically via CI with semver tags and generated changelogs
**Plans**: 3 plans
Plans:
- [x] 05-01-PLAN.md — Uninstall command + packaging manifest (PKG-04, PKG-01)
- [x] 05-02-PLAN.md — CI/CD pipelines + version/changelog management (PKG-05, PKG-06, PKG-07)
- [x] 05-03-PLAN.md — Lifecycle integration tests + migration rollback tests (PKG-02, PKG-03, TEST-03)

### Phase 6: Performance & Observability
**Goal**: Reins is measurably faster than Trellis and provides full execution visibility
**Depends on**: Phase 1
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, OBS-01, OBS-02, OBS-03, OBS-04, OBS-05
**Success Criteria** (what must be TRUE):
  1. Context compilation completes in <500ms for typical spec sets (benchmarked)
  2. CLI starts in <300ms cold, <100ms warm (measured in CI)
  3. Event loop starvation is detected and reported before it impacts user experience
  4. Any past execution point can be replayed via time-travel debugging from the event journal
  5. Traces propagate OpenTelemetry-compatible context across all layers with correlation IDs
**Plans**: 3 plans
Plans:
- [x] 06-01-PLAN.md — Performance benchmarks + CLI startup optimization (PERF-01, PERF-02, PERF-04)
- [x] 06-02-PLAN.md — OpenTelemetry tracing + correlation ID propagation (OBS-01, OBS-02, OBS-03, OBS-05)
- [x] 06-03-PLAN.md — Event loop monitoring + time-travel CLI command (PERF-03, OBS-04)

### Phase 7: Integrations
**Goal**: Reins orchestrates agent work through external issue trackers and communication tools
**Depends on**: Phase 5
**Requirements**: INT-01, INT-02, INT-03, INT-04
**Success Criteria** (what must be TRUE):
  1. Agent runs can be spawned automatically from GitHub issue or Linear ticket state changes
  2. PR creation, issue tracking, and status checks work end-to-end with GitHub
  3. Slack receives notifications and approval requests with actionable responses
  4. Linear issues stay synchronized with Reins task state bidirectionally
**Plans**: 3 plans
Plans:
- [x] 07-01-PLAN.md — GitHub PR creation + status checks + webhook triggers (INT-01, INT-02)
- [x] 07-02-PLAN.md — Slack approval flow + interactive messages (INT-03)
- [x] 07-03-PLAN.md — Linear bidirectional sync + integration trigger tests (INT-01, INT-04)

### Phase 8: Documentation & Developer Experience
**Goal**: A new user goes from zero to productive in under 5 minutes with clear guidance at every step
**Depends on**: Phase 5
**Requirements**: DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, DOC-06, DX-01, DX-02, DX-03, DX-04, DX-05
**Success Criteria** (what must be TRUE):
  1. API reference is auto-generated from type annotations and stays current with code changes
  2. Quick-start guide takes a user from install to first completed task in under 5 minutes
  3. `reins doctor` diagnoses common setup issues and suggests fixes
  4. Shell completion works for all commands in bash, zsh, and fish
  5. Every error message includes a recovery suggestion and documentation link
**Plans**: 3 plans
Plans:
- [x] 08-01-PLAN.md — Doctor command + structured error messages (DX-01, DX-04, DX-05)
- [x] 08-02-PLAN.md — API reference generation + quick-start guide (DOC-01, DOC-02)
- [x] 08-03-PLAN.md — Architecture guide + error recovery tests (DOC-03, DOC-04, DX-05)

### Phase 9: Testing Infrastructure & CI
**Goal**: The test suite provides >90% coverage with property-based, integration, and replay tests running across platforms
**Depends on**: Phase 5, Phase 6
**Requirements**: TEST-01, TEST-02, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. Unit test coverage exceeds 90% for kernel, policy, and execution layers
  2. Property-based tests (hypothesis) verify reducer invariants with thousands of generated cases
  3. CI infrastructure runs integration tests against real git repositories on every push
  4. Historical event replay fixtures pass, proving backward compatibility across versions
  5. CI matrix runs green on Python 3.12+ across Linux and macOS
**Plans**: 3 plans
Plans:
- [x] 09-01-PLAN.md — Coverage measurement + coverage gate in CI (TEST-01, TEST-06)
- [x] 09-02-PLAN.md — Historical replay fixtures + expanded property tests (TEST-02, TEST-05)
- [x] 09-03-PLAN.md — Integration test infrastructure + CI matrix validation (TEST-03, TEST-06)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9
Note: Phase 6 can begin after Phase 1 (parallel with 2-5). Phase 9 can begin after Phase 5+6.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Kernel Hardening | 4/4 | Complete | 2026-05-11 |
| 2. Security & Policy | 3/3 | Complete | 2026-05-11 |
| 3. Platform Parity | 3/3 | Complete | 2026-05-11 |
| 4. Workflow UX & Skills | 3/3 | Complete | 2026-05-11 |
| 5. Migration & Packaging | 3/3 | Complete | 2026-05-11 |
| 6. Performance & Observability | 3/3 | Complete | 2026-05-11 |
| 7. Integrations | 3/3 | Complete | 2026-05-11 |
| 8. Documentation & Developer Experience | 3/3 | Complete | 2026-05-11 |
| 9. Testing Infrastructure & CI | 3/3 | Complete | 2026-05-11 |
