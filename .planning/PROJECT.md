# Reins — Event-Sourced Agent Control Kernel

## What This Is

Reins is a Python-native harness engineering framework that provides event-sourced agent orchestration, policy-driven execution, and progressive context injection for AI coding agents. It must surpass Trellis (the TypeScript reference at `.memo/Trellis`) in every measurable engineering dimension.

## Core Value

**Deterministic, auditable agent control** — every agent action is event-sourced, policy-gated, and traceable. Where Trellis provides a template-based harness, Reins provides a kernel with formal guarantees.

## Context

- **Domain:** AI coding harness / agent control framework
- **Language:** Python 3.11+ (async-first, event-sourced)
- **Competitor:** Trellis (TypeScript, npm, template-based, 14+ platform configurators)
- **Differentiator:** Event sourcing kernel with CQRS, policy engine, time-travel debugging, parallel execution, MCP transport
- **Target users:** Teams running AI coding agents at scale who need reliability, auditability, and extensibility

## Competitive Position

### Reins Advantages (preserve and strengthen)
- Event-sourced kernel with reducers, snapshots, time-travel
- Policy engine with capability-based access control and risk tiers
- Parallel execution with MCP transport layer
- Observability/tracing infrastructure (structlog + ULID traces)
- Evaluation framework (lint, spec, test evaluators)
- Isolation via worktree management
- External integrations (GitHub, Jira, Linear, Slack)
- Python ecosystem (easier to extend for ML/AI teams)

### Trellis Advantages (must match or exceed)
- 14+ platform configurators (Claude, Cursor, Codex, Gemini, Copilot, Windsurf, Kiro, etc.)
- Published package with proper release pipeline (npm, semver, changelogs)
- Comprehensive test suite (unit + integration, vitest)
- Migration system with version tracking and template hashing
- Documentation site with guides and real-world scenarios
- Community presence (Discord, forums, badges)
- Polished CLI UX (init, update, uninstall with interactive prompts)
- Multi-platform hook generation (Python hooks for each platform)
- Template system with hash-based update detection

## Requirements

### Validated

- ✓ Event-sourced kernel with CQRS — existing (`src/reins/kernel/`)
- ✓ Policy engine with approval ledgers — existing (`src/reins/policy/`)
- ✓ Execution adapters (fs, git, shell, MCP) — existing (`src/reins/execution/`)
- ✓ Context compilation with token budgets — existing (`src/reins/context/`)
- ✓ Task lifecycle management — existing (`src/reins/task/`)
- ✓ Multi-agent orchestration — existing (`src/reins/orchestration/`)
- ✓ Platform configurators (Claude, Cursor, Codex) — existing (`src/reins/platform/`)
- ✓ CLI with typer/rich — existing (`src/reins/cli/`)
- ✓ Workspace/journal system — existing (`src/reins/workspace/`)
- ✓ Skill discovery and resolution — existing (`src/reins/skill/`)
- ✓ Hook system — existing (`src/reins/hooks/`)
- ✓ Observability/tracing — existing (`src/reins/observability/`)
- ✓ Worktree isolation — existing (`src/reins/isolation/`)

### Active

- [ ] Platform parity: 14+ configurators matching Trellis coverage
- [ ] Release pipeline: PyPI publishing, semver, changelogs, CI/CD
- [ ] Test coverage: >90% with unit + integration + property-based tests
- [ ] Migration system: version-aware upgrades with rollback
- [ ] Documentation: comprehensive docs site with guides
- [ ] Template hashing: detect stale platform configs
- [ ] CLI polish: interactive init, update, uninstall flows
- [ ] Benchmarks: performance comparison vs Trellis on real workloads
- [ ] Security audit: formal threat model, input validation, sandboxing
- [ ] API stability: versioned public API with deprecation policy
- [ ] Error handling: structured errors with recovery suggestions
- [ ] Examples: real-world usage scenarios with working code
- [ ] Packaging: single `pip install reins` with optional extras
- [ ] Developer experience: <30s setup, clear error messages, helpful defaults

### Out of Scope

- GUI/web dashboard — CLI and API only for v1
- Cloud-hosted service — local-first, self-contained
- Non-Python agent runtimes — Python kernel only (agents can be any language)
- Billing/metering — not a SaaS product

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python over TypeScript | ML/AI ecosystem alignment, async-first, type safety with pydantic | Committed |
| Event sourcing kernel | Deterministic replay, time-travel debugging, audit trail | Committed |
| CQRS pattern | Separate read/write paths for scalability and testability | Committed |
| Capability-based policy | Fine-grained access control without ambient authority | Committed |
| MCP as execution transport | Standard protocol for agent-tool communication | Committed |
| Surpass Trellis as benchmark | Measurable engineering criteria, not subjective claims | Active |

## Comparison Dimensions

The following 14 dimensions define "surpassing Trellis":

1. **Architecture** — formal kernel vs template scripts
2. **Feature coverage** — all Trellis features + unique Reins capabilities
3. **API design** — typed, versioned, documented public surface
4. **Extensibility** — plugin system, adapter pattern, hook points
5. **Reliability** — event sourcing guarantees, crash recovery, idempotency
6. **Testability** — pure functions, dependency injection, test helpers
7. **Developer experience** — setup time, error messages, documentation
8. **Documentation** — API docs, guides, examples, architecture docs
9. **Examples** — working scenarios for common use cases
10. **Performance** — startup time, context compilation speed, memory usage
11. **Security** — sandboxing, policy engine, input validation
12. **Maintainability** — code quality, modularity, dependency management
13. **Packaging/release** — CI/CD, versioning, distribution
14. **Integration surface** — platforms supported, external services

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-11 after initialization*
