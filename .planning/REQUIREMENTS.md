# Requirements

## v1 Requirements

### Kernel Integrity (KERN)

- [ ] **KERN-01**: Event schema supports versioned types with upcaster registry for forward-compatible replay
- [ ] **KERN-02**: Snapshot store validates integrity on load and rebuilds from journal on corruption
- [ ] **KERN-03**: Reducer functions pass property-based tests (commutativity, idempotency, replay correctness)
- [ ] **KERN-04**: All persisted artifacts embed `reins_version` for migration compatibility
- [ ] **KERN-05**: Duplicate orchestration implementations consolidated into single canonical path
- [ ] **KERN-06**: Event journal supports compaction with configurable retention policy

### Security & Policy (SEC)

- [ ] **SEC-01**: Shell execution adapter uses exec-style invocation, never `shell=True`
- [ ] **SEC-02**: API server binds to localhost by default, requires explicit opt-in for network exposure
- [ ] **SEC-03**: Policy engine enforces capability gates end-to-end with no execution-layer bypass vectors
- [ ] **SEC-04**: Template/registry fetches validate TLS certificates
- [ ] **SEC-05**: Formal threat model documented covering agent sandboxing, data exfiltration, and privilege escalation
- [ ] **SEC-06**: Input validation on all external boundaries (CLI args, API payloads, config files)

### Platform Support (PLAT)

- [ ] **PLAT-01**: Shared template engine generates platform-specific configs from declarative platform descriptors
- [ ] **PLAT-02**: Template hashing detects stale configs and prompts for update
- [ ] **PLAT-03**: Tier 1 platforms (Claude, Cursor, Codex) have full CI coverage with integration tests
- [ ] **PLAT-04**: Tier 2 platforms (Kiro, Gemini, Copilot, Windsurf, OpenCode) have smoke tests and generated configs
- [ ] **PLAT-05**: Tier 3 platforms (Kilo, Antigravity, Qoder, CodeBuddy, Droid, Pi) have generated configs
- [ ] **PLAT-06**: Platform capability contract tests verify each configurator produces valid output
- [ ] **PLAT-07**: Hook generation produces platform-appropriate hooks (Python for Claude/Codex, JS for Cursor/OpenCode)

### Workflow UX (WF)

- [ ] **WF-01**: Per-turn workflow state breadcrumb injected via session-start hook
- [ ] **WF-02**: Brainstorm/planning skill guides PRD creation with structured questioning
- [ ] **WF-03**: Break-loop skill triggers retrospective and knowledge capture
- [ ] **WF-04**: Spec update workflow promotes task learnings back into spec system
- [ ] **WF-05**: Session-scoped task pointer with automatic context injection
- [ ] **WF-06**: Workflow state machine with configurable transitions (planning → in_progress → checking → done)

### Migration & Packaging (PKG)

- [ ] **PKG-01**: Two-layer migration system handles both user configs and internal state (events, snapshots)
- [ ] **PKG-02**: `pip install reins` installs working CLI with all dependencies
- [ ] **PKG-03**: PyPI publishing via Trusted Publishers with automated CI/CD pipeline
- [ ] **PKG-04**: Semantic versioning with automated changelog generation
- [ ] **PKG-05**: `reins init` interactive flow detects project type and generates appropriate configs
- [ ] **PKG-06**: `reins update` upgrades configs with migration support and rollback capability
- [ ] **PKG-07**: `reins uninstall` cleanly removes all generated files

### Testing & Quality (TEST)

- [ ] **TEST-01**: Unit test coverage >90% for kernel, policy, and execution layers
- [ ] **TEST-02**: Property-based tests (hypothesis) verify reducer invariants
- [ ] **TEST-03**: Integration tests exercise full CLI flows on real git repositories
- [ ] **TEST-04**: Platform contract tests validate configurator output against platform schemas
- [ ] **TEST-05**: Historical event replay fixtures ensure backward compatibility
- [ ] **TEST-06**: CI matrix covers Python 3.12+ on Linux and macOS

### Performance (PERF)

- [ ] **PERF-01**: CPU-bound work (tokenization, serialization) offloaded to thread pool
- [ ] **PERF-02**: Event loop latency monitoring with alerting on starvation
- [ ] **PERF-03**: Context compilation completes in <500ms for typical spec sets
- [ ] **PERF-04**: CLI startup time <300ms (cold) and <100ms (warm with cache)
- [ ] **PERF-05**: Benchmark suite comparing Reins vs Trellis on equivalent operations

### Documentation (DOC)

- [ ] **DOC-01**: API reference auto-generated from type annotations and docstrings
- [ ] **DOC-02**: Architecture guide explaining kernel, layers, and data flow
- [ ] **DOC-03**: Quick-start guide: install → init → first task in <5 minutes
- [ ] **DOC-04**: Platform-specific setup guides for each Tier 1 platform
- [ ] **DOC-05**: Real-world examples with working code for common scenarios
- [ ] **DOC-06**: Migration guide for users coming from Trellis

### Developer Experience (DX)

- [ ] **DX-01**: Structured error messages with recovery suggestions and documentation links
- [ ] **DX-02**: Shell completion for all CLI commands (bash, zsh, fish)
- [ ] **DX-03**: `reins doctor` command diagnoses common setup issues
- [ ] **DX-04**: Verbose/debug mode with structured log output for troubleshooting
- [ ] **DX-05**: Configuration validation with helpful error messages on invalid configs

### Observability (OBS)

- [ ] **OBS-01**: Structured logging (structlog) throughout all layers with correlation IDs
- [ ] **OBS-02**: Event journal queryable for audit trail and debugging
- [ ] **OBS-03**: Time-travel debugging: replay to any point in run history
- [ ] **OBS-04**: OpenTelemetry-compatible trace context propagation
- [ ] **OBS-05**: CLI command to inspect current run state and event history

### Integrations (INT)

- [ ] **INT-01**: GitHub integration: PR creation, issue tracking, status checks
- [ ] **INT-02**: Linear integration: issue sync, status updates, auto-spawn from tickets
- [ ] **INT-03**: Slack integration: notifications, approval requests, status updates
- [ ] **INT-04**: Issue-tracker-as-control-plane: auto-spawn agent runs from ticket state changes

---

## v2 Requirements (Deferred)

- [ ] Distributed multi-agent coordination (A2A routing)
- [ ] Plugin registry with community contributions
- [ ] GUI/web dashboard for run visualization
- [ ] Cloud-hosted execution service
- [ ] Model-specific prompt optimization
- [ ] Fleet management across multiple repositories
- [ ] Custom DSL for workflow definition
- [ ] Billing/metering for team usage tracking

---

## Out of Scope

- **GUI/web dashboard** — API-first; let ecosystem build UIs
- **Cloud-hosted service** — local-first, self-contained
- **Non-Python kernel runtime** — Python only (agents can be any language)
- **Billing/metering** — not a SaaS product
- **Model training/fine-tuning** — harness controls agents, doesn't train them
- **IDE plugins** — platform configurators generate configs; IDE integration is the platform's job

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| KERN-01 through KERN-06 | Phase 1 | Pending |
| SEC-01 through SEC-06 | Phase 2 | Pending |
| PLAT-01 through PLAT-07 | Phase 3 | Pending |
| WF-01 through WF-06 | Phase 4 | Pending |
| PKG-01 through PKG-07 | Phase 5 | Pending |
| TEST-01 through TEST-06 | Phase 8 | Pending |
| PERF-01 through PERF-05 | Phase 6 | Pending |
| DOC-01 through DOC-06 | Phase 5 | Pending |
| DX-01 through DX-05 | Phase 5 | Pending |
| OBS-01 through OBS-05 | Phase 6 | Pending |
| INT-01 through INT-04 | Phase 7 | Pending |

---

*Generated: 2026-05-11*
*Total v1 requirements: 56*
*Categories: 10*
