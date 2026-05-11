# Domain Pitfalls

**Domain:** AI coding harness / event-sourced agent control framework
**Researched:** 2026-05-11

## Critical Pitfalls

Mistakes that cause rewrites, user abandonment, or architectural dead ends.

### Pitfall 1: Event Schema Ossification

**What goes wrong:** The event schema (`EventEnvelope.payload`) becomes impossible to evolve without breaking replay. Reins currently uses `schema_version: int = 1` on envelopes but has no upcasting pipeline. As the kernel evolves, old events stored as JSON become unreadable by new reducers, or worse, silently produce incorrect state.

**Why it happens:** Event sourcing's immutability guarantee means you cannot modify stored events. Teams add fields to payloads, rename event types, or change semantics without building a versioned deserialization layer. The problem compounds because it is invisible until someone tries to replay an old run.

**Consequences:**
- Time-travel debugging breaks silently (wrong state reconstructed from old events)
- Snapshots become the only reliable path, defeating the purpose of event sourcing
- Users lose trust in the audit trail
- Forced to choose between "never change events" (stagnation) or "break old data" (data loss)

**Warning signs:**
- Adding `.get("field", default)` calls in reducers to handle missing fields
- Snapshot store becoming the de facto source of truth
- Tests that only use recently-created events, never replaying historical ones

**Prevention:**
- Implement an upcaster registry: a chain of transformers that convert event v1 -> v2 -> v3 at read time
- Version event types explicitly (e.g., `task.started.v2` or a `schema_version` per event type, not just on the envelope)
- Add a replay integration test that loads events from every historical schema version
- Never remove fields from event payloads; only add with defaults

**Phase to address:** Early (before any public release). Once events are persisted by users, the schema is a public API.

---

### Pitfall 2: Over-Engineering the Event Sourcing Kernel

**What goes wrong:** The team invests heavily in event sourcing infrastructure (projections, CQRS read models, complex reducer chains, event bus pub/sub) when the actual user need is "configure my AI agent and run it reliably." The kernel becomes an intellectual exercise that slows feature delivery.

**Why it happens:** Event sourcing is architecturally elegant and fun to build. Engineers optimize for theoretical purity (every state change must be an event) rather than user value. The Reins kernel already has 820 lines in `orchestrator.py` — a sign of growing complexity.

**Consequences:**
- Simple features (add a new platform configurator) require touching the event system
- Onboarding new contributors takes weeks instead of hours
- Users who just want `pip install reins && reins init` bounce off the complexity
- Trellis (simpler template approach) wins on time-to-value despite inferior architecture

**Warning signs:**
- New features require creating new event types, reducers, and projections before any user-visible behavior
- Contributors ask "where do I put this?" and the answer involves 4+ files
- The ratio of kernel infrastructure code to user-facing feature code exceeds 2:1

**Prevention:**
- Draw a hard boundary: the kernel handles run lifecycle and audit. Platform configurators, CLI, and integrations operate outside the event system.
- Not everything needs to be an event. Configuration changes, template updates, and platform detection are stateless operations.
- Measure "lines of code to add a new platform configurator" — if it exceeds 100 lines, the abstraction is too heavy.
- Keep the kernel's public API surface small: `start_run()`, `emit_event()`, `get_state()`, `replay()`.

**Phase to address:** Ongoing architectural discipline. Establish the boundary now before adding 11 more platform configurators.

---

### Pitfall 3: Platform Configurator Combinatorial Explosion

**What goes wrong:** Supporting 14+ platforms (Claude, Cursor, Codex, Gemini, Copilot, Windsurf, Kiro, etc.) creates an N x M maintenance matrix where N = platforms and M = features (hooks, agents, settings, templates, context formats). Each platform evolves independently, and keeping all configurators working becomes a full-time job.

**Why it happens:** AI coding platforms are evolving at unprecedented speed. Claude Code added hooks in late 2025. Codex gained computer use in April 2026. Cursor had breaking changes in March 2026 (code reversion bugs). Each platform has different config formats, capability sets, and update cadences.

**Consequences:**
- Configurators for less-popular platforms rot silently (no one tests them)
- A platform API change breaks users who upgraded Reins but not the platform
- Template drift: platform templates diverge from actual platform requirements
- Maintenance burden grows linearly with platforms but value grows sub-linearly (most users use 1-2 platforms)

**Warning signs:**
- Platform-specific bug reports that only reproduce on one platform
- Template files that haven't been updated in 3+ months
- CI that doesn't test all platform configurators against real platform versions
- Users reporting "reins init worked but the agent doesn't actually run"

**Prevention:**
- Implement a platform capability contract test: each configurator must pass a standard validation suite
- Use the existing `TemplateHashStore` to detect stale templates, but also add platform version detection
- Tier platforms: Tier 1 (Claude, Cursor, Codex) get full CI coverage; Tier 2 (community-contributed) get basic smoke tests
- Design configurators as thin adapters over a shared template engine, not as independent implementations
- Add a `reins doctor` command that validates the current platform config against the installed platform version
- Pin platform compatibility ranges (e.g., "works with Claude Code >= 1.0.30")

**Phase to address:** Before scaling beyond 3 platforms. The current 3-configurator architecture must prove the pattern works before adding 11 more.

---

### Pitfall 4: Async Event Loop Starvation

**What goes wrong:** The async Python event system blocks the event loop during CPU-bound operations (token estimation, JSON serialization of large event payloads, snapshot computation, template rendering). This causes cascading latency in multi-agent orchestration where multiple agents share a single event loop.

**Why it happens:** Python's asyncio is single-threaded. The current token estimation (`len(text) // 4`) is cheap, but replacing it with `tiktoken` (as CONCERNS.md suggests) introduces CPU-bound work. Similarly, `canonical_json()` for checksum computation, snapshot serialization, and event journal writes can block when payloads are large.

**Consequences:**
- Agent responses feel sluggish even when the AI platform responds quickly
- Multi-agent workflows serialize instead of running in parallel
- Timeout errors in MCP sessions because the event loop was blocked during event processing
- Hard to diagnose: profiling async code is notoriously difficult

**Warning signs:**
- `asyncio` debug mode warnings about slow callbacks (>100ms)
- MCP session timeouts that correlate with large event payloads
- Parallel executor (`parallel_executor.py` at 11.5K) not achieving actual parallelism
- Users reporting "it was fast with one agent but slow with three"

**Prevention:**
- Run CPU-bound work in `asyncio.to_thread()` or a `ProcessPoolExecutor` — especially tokenization, JSON serialization, and checksum computation
- Add event loop latency monitoring: measure time between `await` yields
- Set `asyncio` slow callback threshold in development mode
- Profile with `yappi` or `py-spy` in async mode before claiming performance targets
- Keep event payloads small (store references to large data, not the data itself)
- Consider `uvloop` as a drop-in replacement for the default event loop (2-4x throughput improvement)

**Phase to address:** Before performance benchmarking phase. Must be addressed before claiming "faster than Trellis."

---

### Pitfall 5: Migration System That Can't Migrate Itself

**What goes wrong:** The migration system is designed for user-facing config upgrades (template hashing, version tracking) but doesn't handle migrations of Reins' own internal state — event journals, snapshots, policy ledgers, workspace journals. When Reins itself upgrades, users' existing runs become unreadable.

**Why it happens:** Migration systems are typically designed for one direction: upgrading user-facing artifacts. But an event-sourced system has internal persistent state that also needs migration. The `SnapshotStore` currently deserializes with hardcoded field access (`data["snapshot_id"]`, `data["run_id"]`) — any schema change breaks existing snapshots.

**Consequences:**
- Users upgrading Reins lose access to historical runs
- "Works on fresh install, breaks on upgrade" — the worst kind of bug
- Rollback becomes impossible if the migration is destructive
- Users avoid upgrading, fragmenting the installed base

**Warning signs:**
- Adding new fields to `StateSnapshot` or `EventEnvelope` without a migration step
- Tests that always start from empty state, never from a previous version's persisted data
- No version marker in persisted JSON files
- Users reporting "I upgraded and now `reins replay` crashes"

**Prevention:**
- Embed a `reins_version` field in all persisted artifacts (events, snapshots, journals)
- Build a two-layer migration system: (1) user config migrations (templates, platform configs) and (2) internal state migrations (events, snapshots)
- Test upgrades: maintain a fixture directory with artifacts from each released version
- Make migrations reversible where possible (keep old fields, add new ones)
- Never deserialize with positional/required field access — always use `.get()` with defaults for new fields

**Phase to address:** Before first public release (PyPI). Once users have persisted state, you own backward compatibility.

---

### Pitfall 6: Security Theater in the Policy Engine

**What goes wrong:** The capability-based policy engine provides a false sense of security. It gates agent actions through approval ledgers, but the actual execution path has bypass vectors: shell injection via `create_subprocess_shell`, unauthenticated API server on 0.0.0.0, hook commands with `shell=True`, and no TLS verification on remote registry fetches.

**Why it happens:** Policy engines are designed top-down (what should be allowed?) while security vulnerabilities are bottom-up (what can actually be exploited?). The policy engine is architecturally sound but the execution layer has gaps that make the policies unenforceable.

**Consequences:**
- Users trust the policy engine to sandbox agents, but a malicious MCP tool or compromised hook can bypass it entirely
- A security audit reveals the gap, destroying credibility
- Worse: a real exploit occurs in production, and the "policy-gated" marketing claim becomes a liability

**Warning signs:**
- Policy engine tests that mock the execution layer (testing the gate without testing the wall)
- No integration tests that attempt policy bypass through execution-layer vulnerabilities
- Security documentation that describes the policy model but not the threat model
- `shell=True` anywhere in the execution path

**Prevention:**
- Conduct a formal threat model: enumerate all paths from external input to system calls
- Replace `create_subprocess_shell` with `create_subprocess_exec` (argument lists, not strings) — this is already flagged in CONCERNS.md
- Bind the API server to 127.0.0.1 by default, require explicit opt-in for network binding
- Add integration tests that attempt to escape the policy sandbox through known vectors
- Separate "policy" (what the agent is allowed to do) from "isolation" (what the system prevents regardless of policy)
- Document the security boundary clearly: "Policy engine controls agent intent. Worktree isolation controls blast radius. Neither is a substitute for the other."

**Phase to address:** Before any security claims in documentation or marketing. Address execution-layer gaps before the security audit phase.

---

## Moderate Pitfalls

### Pitfall 7: Test Suite That Tests Mocks, Not Behavior

**What goes wrong:** The test suite achieves high coverage by mocking the event journal, MCP sessions, platform APIs, and file system — but doesn't catch real bugs because the mocks don't match actual behavior. The 141 test files test internal implementation details rather than user-observable outcomes.

**Warning signs:**
- Tests break when refactoring internals (even if behavior is unchanged)
- Tests pass but users report bugs in the exact scenarios "covered" by tests
- Mock setup code is longer than the actual test assertion
- No tests that run `reins init` end-to-end on a real repository

**Prevention:**
- Add a small suite of end-to-end tests that exercise real CLI commands on real (temporary) git repos
- For the kernel: test by replaying real event sequences and asserting final state, not by mocking individual method calls
- For platform configurators: test by running `configure()` on a real directory and validating the output files
- Use property-based testing (Hypothesis) for the reducer: generate random event sequences and verify invariants hold
- Target the "testing trophy" shape: many integration tests, fewer unit tests for pure logic, minimal mocks

**Phase to address:** Test infrastructure phase. Establish the pattern before scaling to 14+ platforms.

---

### Pitfall 8: Documentation That Describes Architecture, Not Usage

**What goes wrong:** Documentation explains the event sourcing kernel, CQRS pattern, and policy engine in detail — but doesn't answer "how do I configure Reins for my Claude Code project in 5 minutes?" Users who need the tool can't figure out how to use it; users who understand the architecture don't need the docs.

**Warning signs:**
- README leads with architecture diagrams instead of quickstart
- No copy-pasteable examples that work without modification
- Documentation references internal types (`EventEnvelope`, `StateSnapshot`) in user-facing guides
- Users ask basic "how do I..." questions that should be answered by docs

**Prevention:**
- Write docs from the user's perspective: "I have a Python project and want to use Claude Code with guardrails"
- Lead with a 30-second quickstart: `pip install reins && cd my-project && reins init --platform claude`
- Separate user docs (how to use) from contributor docs (how it works internally)
- Add a "cookbook" with real scenarios: "Setting up multi-agent review", "Adding a custom policy", "Migrating from Trellis"
- Test documentation: run every code example in CI

**Phase to address:** Documentation phase, but the quickstart should exist from day one of public release.

---

### Pitfall 9: Premature Abstraction in the Orchestration Layer

**What goes wrong:** The orchestration layer has duplicate implementations (two SubagentManagers, two MCP session managers, two orchestrators) because abstractions were created before the actual usage patterns were clear. Adding more abstraction layers to "fix" the duplication makes it worse.

**Warning signs:**
- New features require choosing between two similar-but-different code paths
- Contributors implement features in the wrong module because the boundaries are unclear
- The `orchestration/` package re-wraps `execution/` package functionality with minimal added value
- Method signatures grow to accommodate both use cases, with many optional parameters

**Prevention:**
- Consolidate before expanding: merge the duplicate implementations NOW (as flagged in CONCERNS.md) before adding more platforms or agents
- Apply the "rule of three": don't abstract until you have three concrete use cases that share a pattern
- Name things by what they DO, not by architectural role: `spawn_local_agent()` vs `spawn_mcp_agent()` instead of two `SubagentManager` classes
- If two modules have overlapping responsibilities, one should depend on the other (layering) or they should merge

**Phase to address:** Immediately, before any new feature work. Tech debt compounds.

---

### Pitfall 10: Snapshot Invalidation Cascade

**What goes wrong:** Snapshots become invalid when reducers change, but there's no mechanism to detect or handle this. The `StateSnapshot` has a `reducer_version` field, but if a reducer bug is fixed or behavior changes, all existing snapshots produce incorrect state when used as replay starting points.

**Warning signs:**
- Bugs that only appear when replaying from a snapshot (not from event zero)
- `reducer_version` never actually increments
- No test that compares "replay from zero" vs "replay from snapshot" for consistency
- Users report different behavior for old runs vs new runs

**Prevention:**
- Implement snapshot validation: after loading a snapshot, replay a few subsequent events and compare against full replay (spot-check)
- Increment `reducer_version` on ANY reducer logic change, not just schema changes
- Add a `reins verify-run` command that checks snapshot consistency
- Consider snapshot expiry: snapshots older than N versions are automatically invalidated and rebuilt on next access
- Store the reducer code hash alongside the snapshot for tamper detection

**Phase to address:** Before time-travel debugging is marketed as a feature.

---

### Pitfall 11: Community Building Before Product-Market Fit

**What goes wrong:** Investing in Discord servers, contributor guides, badges, and community presence before the core product reliably solves a real problem. Early adopters arrive, hit rough edges, leave, and never come back. First impressions are permanent in open source.

**Warning signs:**
- Community channels exist but have more questions than answers
- Contributors open PRs but maintainers can't review them fast enough
- Users try the tool once, file an issue, and never return
- Marketing claims ("surpasses Trellis") that the product can't yet substantiate

**Prevention:**
- Sequence: working product -> early adopters (private) -> polish based on feedback -> public launch -> community
- Find 3-5 "design partners" who use Reins in real workflows and iterate with them before going public
- Don't claim superiority over Trellis until benchmarks prove it on the 14 dimensions
- Community infrastructure (Discord, docs site) should launch WITH the stable release, not before
- Make the first-run experience flawless: `reins init` must work perfectly on the first try

**Phase to address:** After stable release, not before.

---

## Minor Pitfalls

### Pitfall 12: Token Budget Estimation Drift

**What goes wrong:** The `len(text) // 4` token estimation diverges significantly from actual tokenizer counts, causing context windows to be under- or over-filled by 30-50%. This leads to truncated context (agent misses critical information) or wasted budget (agent could have received more context).

**Prevention:**
- Use `tiktoken` for accurate counts (run in a thread pool to avoid blocking)
- Cache token counts for unchanged files
- Add a "context budget utilization" metric to observability

**Phase to address:** Performance optimization phase.

---

### Pitfall 13: Git Worktree Orphaning

**What goes wrong:** The worktree manager's cleanup has multiple `except Exception` blocks that swallow errors. If cleanup partially fails, git worktrees are left in orphaned states that confuse subsequent operations and waste disk space.

**Prevention:**
- Track cleanup state explicitly (which steps completed, which failed)
- Add a `reins cleanup --orphaned` command for manual recovery
- Log cleanup failures at WARNING level, not silently swallow them
- Add a periodic health check that detects orphaned worktrees

**Phase to address:** Reliability phase, before multi-agent workflows are common.

---

### Pitfall 14: Logging Inconsistency Across Modules

**What goes wrong:** Only 7 of 174 source files use `logging.getLogger`. Some use `print()`. Most have no logging at all. When something goes wrong in production, there's no trail to follow.

**Prevention:**
- Adopt `structlog` consistently (it's already in the observability module)
- Add a linting rule that flags `print()` in non-CLI code
- Establish log levels: DEBUG for event replay details, INFO for lifecycle events, WARNING for recoverable errors, ERROR for failures
- Ensure every async boundary (MCP call, subprocess, file I/O) has entry/exit logging at DEBUG level

**Phase to address:** Early infrastructure phase. Logging is foundational for debugging everything else.

---

### Pitfall 15: Dependency Pinning vs Flexibility

**What goes wrong:** Either dependencies are pinned too tightly (users can't install Reins alongside other packages due to version conflicts) or too loosely (Reins breaks when a dependency releases a breaking change). For a framework that other tools depend on, this balance is critical.

**Prevention:**
- Use version ranges in `pyproject.toml` (e.g., `pydantic>=2.0,<3.0`) but pin exact versions in a lockfile for CI
- Test against both minimum and maximum supported versions of key dependencies
- Keep the dependency tree shallow: fewer transitive dependencies = fewer conflicts
- Consider making heavy dependencies optional extras (`pip install reins[tiktoken]`, `pip install reins[uvloop]`)

**Phase to address:** Packaging/release phase.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Platform parity (14+ configurators) | Combinatorial explosion (#3) | Tier platforms, shared template engine, capability contract tests |
| Release pipeline (PyPI) | Migration system gaps (#5) | Version-stamp all persisted artifacts before first release |
| Test coverage (>90%) | Testing mocks not behavior (#7) | Integration tests on real repos, property-based kernel tests |
| Migration system | Self-migration blind spot (#5) | Two-layer migration: user configs + internal state |
| Documentation | Architecture-first docs (#8) | User-perspective quickstart, tested code examples |
| Security audit | Security theater (#6) | Threat model first, fix execution-layer gaps before policy claims |
| Performance benchmarks | Event loop starvation (#4) | Profile async paths, offload CPU work to threads |
| API stability | Event schema ossification (#1) | Upcaster registry, versioned event types, replay tests |
| Community building | Premature community (#11) | Private design partners first, public launch after stability |
| Tech debt consolidation | Premature abstraction (#9) | Merge duplicates before adding new features |

## Sources

- [Event Sourcing Pattern - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [The dark side of event sourcing (research paper)](https://www.researchgate.net/publication/315637858_The_dark_side_of_event_sourcing_Managing_data_conversion)
- [CQRS and Event Sourcing at Scale](https://uplatz.com/blog/cqrs-and-event-sourcing-at-scale-a-strategic-analysis-of-real-world-implementation-challenges/)
- [How to Implement Event Versioning Strategies](https://oneuptime.com/blog/post/2026-01-30-event-driven-versioning-strategies/view)
- [Event-Driven Systems Best Practices (2026)](https://tutorialq.com/microservices/patterns/event-drive-systems-best-practices)
- [AsyncIO Pitfalls and Performance](http://runebook.dev/en/docs/python/library/asyncio-eventloop)
- [Python asyncio shared state problems](https://www.inngest.com/blog/no-lost-updates-python-asyncio)
- [Harness Engineering: The Discipline That Determines Whether Your AI Agents Actually Work](https://tianpan.co/blog/2026-02-17-harness-engineering-agent-first-software-development)
- [Anthropic: Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [How Stripe Ships 1,300 AI PRs a Week: Harness Engineering](https://www.mindstudio.ai/blog/what-is-harness-engineering-beyond-prompt-context-engineering)
- [Cursor Problems 2026: Crashes, Costs & Workarounds](https://vibecoding.app/blog/cursor-problems-2026)
- [Why Prototypes Fail to Scale](https://azumo.com/artificial-intelligence/ai-insights/open-weight-ai-prototype-to-production)
- [An Empirical Characterization of Event Sourced Systems and Their Schema Evolution](https://arxiv.org/abs/2104.01146)
- [Event Snapshotting Implementation](https://oneuptime.com/blog/post/2026-01-30-event-snapshotting/view)

---

*Pitfalls audit: 2026-05-11*
