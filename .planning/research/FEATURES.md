# Feature Landscape

**Domain:** AI coding harness / agent control framework
**Researched:** 2026-05-11
**Competitor benchmark:** Trellis v0.5 (TypeScript, 14 platform configurators)

## Table Stakes

Features users expect from any serious AI coding harness. Missing = product feels incomplete or amateur.

| Feature | Why Expected | Complexity | Reins Status | Trellis Status |
|---------|--------------|------------|--------------|----------------|
| Multi-platform config generation | Teams use 3+ AI tools; harness must support all of them | High | Partial (3: Claude, Cursor, Codex) | Strong (14 platforms) |
| Task lifecycle management | Every agent session needs bounded scope; tasks are the unit of work | Med | Exists | Exists |
| Spec/guideline injection | Agents need project standards loaded per-turn without stuffing full context | Med | Exists (ContextCompilerV2) | Exists (spec system + jsonl) |
| Workflow state machine | Plan-Execute-Finish is the universal loop; agents need phase awareness | Med | Exists (workflow module) | Exists (workflow.md + breadcrumbs) |
| Session memory / journals | Context compaction kills memory; file-based persistence survives | Low | Exists (workspace) | Exists (workspace journals) |
| CLI with init/update/uninstall | Entry point for adoption; must be frictionless | Med | Exists (typer/rich) | Exists (npm CLI) |
| Hook system | Platform events (tool use, prompt submit) trigger harness logic | Med | Exists | Exists (per-platform hooks) |
| Sub-agent dispatch | Complex tasks need implement/check/research delegation | High | Exists (orchestration) | Exists (skill routing) |
| Migration system | Users upgrade versions; configs must migrate without manual work | Med | Exists (engine.py) | Exists (manifest-based) |
| Skill/capability discovery | Agents need to find and load the right behavior at the right time | Med | Exists (skill module) | Exists (skills per platform) |
| Template hashing / staleness detection | Generated platform files drift; detect when regeneration needed | Low | Exists (template_hash.py) | Exists |
| Developer identity / workspace isolation | Multi-developer repos need per-person state | Low | Exists | Exists |

## Differentiators

Features that set Reins apart. Not expected by default, but create competitive advantage.

| Feature | Value Proposition | Complexity | Reins Status | Trellis Gap |
|---------|-------------------|------------|--------------|-------------|
| Event-sourced kernel | Every agent action is an immutable event; enables replay, audit, time-travel debugging | High | Exists (kernel/) | Not present — Trellis has no event log |
| Policy engine with risk tiers | Capability-based access control prevents destructive actions without blanket blocking | High | Exists (policy/) | Not present — Trellis relies on workflow text constraints |
| Deterministic replay / time-travel | Rebuild any past run state from events; debug failures by replaying | High | Exists (reducer + snapshots) | Not present |
| Parallel execution with worktree isolation | Multiple agents work simultaneously in isolated git worktrees | High | Exists (isolation/) | Not present — Trellis is single-session |
| Evaluation framework | Automated quality gates (lint, spec compliance, test) with typed failure classification | Med | Exists (evaluation/) | Partial — Trellis has check skill but no formal eval framework |
| MCP transport layer | Standard protocol for agent-tool communication; future-proof | Med | Exists (execution adapters) | Not present |
| External service integrations | GitHub, Jira, Linear, Slack as first-class citizens for issue-tracker-as-control-plane | Med | Exists (integrations/) | Not present — Trellis is repo-local only |
| Dehydration/hydration for durable runs | Serialize full run state for crash recovery and long-running tasks | High | Exists (kernel) | Not present |
| Token-budgeted context assembly | Three-tier context (standing law, task contract, spec shards) with audit trail | Med | Exists (context/) | Partial — Trellis injects via jsonl but no budget management |
| Approval ledger for high-risk ops | Human-in-the-loop with structured approval records | Med | Exists (approval/) | Not present |
| Pipeline DAG orchestration | Declarative multi-stage workflows with dependency graphs | High | Exists (orchestration/pipeline) | Not present — Trellis is linear phase flow |
| HTTP API for programmatic control | External systems can manage runs without CLI | Med | Exists (api/) | Not present |
| Observability / structured tracing | ULID-based trace IDs, causation chains, structured events | Med | Exists (observability/) | Not present |
| Issue-tracker-as-control-plane | Symphony-style: poll tracker, claim tasks, spawn agents automatically | High | Partial (Linear integration) | Not present |
| Checkpoint/resume for long runs | Persist progress at stable boundaries; resume without restart | Med | Exists (memory/checkpoint) | Not present |

## Features Trellis Does Well (learn from)

| Feature | What Trellis Gets Right | Implication for Reins |
|---------|------------------------|----------------------|
| Platform breadth | 14 configurators with per-platform skill/agent/hook generation | Must reach parity; 3 is not competitive |
| Workflow breadcrumb injection | Per-turn state breadcrumb tells agent exactly what phase it's in | Reins workflow module should emit equivalent per-turn context |
| Brainstorm skill | Structured requirements discovery with research-first, one-question-at-a-time | Reins needs equivalent guided planning capability |
| Break-loop skill | Deep bug analysis to prevent fix-forget-repeat cycles | Reins evaluation framework should incorporate this pattern |
| Spec update skill | Captures institutional memory from debugging/implementation back into specs | Reins needs a knowledge-capture workflow |
| Sub-agent context injection | implement.jsonl / check.jsonl curate exactly what sub-agents see | Reins context compiler already does this better (token budgets) |
| Session-scoped active task | Per-session task pointer with platform-native session identity | Reins task system should support session-scoped pointers |
| Task hierarchy (parent/child) | Complex tasks decompose into subtasks with explicit relationships | Reins task module should support hierarchical decomposition |
| Inline vs dispatch modes | Adapts to platform capabilities (sub-agent vs main-session) | Reins orchestration should detect and adapt to platform class |
| Community/docs presence | Discord, docs site, forum posts, badges, star history | Reins needs equivalent community infrastructure |

## Features Trellis Misses (Reins advantages to exploit)

| Gap in Trellis | Why It Matters | Reins Advantage |
|----------------|----------------|-----------------|
| No event log / audit trail | Can't answer "what did the agent do and why?" after the fact | Event-sourced kernel provides complete audit |
| No policy engine | Relies on text-based "don't do X" instructions that agents ignore under pressure | Formal capability evaluation with allow/ask/deny |
| No parallel execution | One agent, one task, one session at a time | Worktree isolation enables fleet-of-agents |
| No crash recovery | If session dies mid-task, state is lost | Dehydration/hydration + checkpoints |
| No formal verification | "trellis-check" is a prompt, not a typed evaluator | Evaluation framework with failure classification |
| No external integrations | Repo-local only; can't connect to issue trackers or notification systems | GitHub/Jira/Linear/Slack integrations |
| No token budget management | Injects all jsonl-referenced files regardless of context window | Three-tier budgeted assembly with overflow handling |
| No programmatic API | CLI-only; can't integrate into CI/CD or external orchestrators | HTTP API + MCP transport |
| No deterministic replay | Can't reproduce a failure or understand what went wrong | Event replay from journal |
| Template-based, not kernel-based | Scripts parse markdown; no formal state machine | Pure reducer functions with typed state transitions |
| No risk assessment | All operations treated equally | Tiered risk (T0-T4) with appropriate gates |
| No observability | No structured logging, no trace IDs, no causation chains | structlog + ULID traces + causation |

## Anti-Features

Features to explicitly NOT build. These are traps.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| GUI/web dashboard | Splits focus, adds maintenance burden, not what CLI-first users want | Expose HTTP API; let others build UIs on top |
| Cloud-hosted service | Violates local-first principle; introduces auth/billing/infra complexity | Stay self-contained; provide deployment guides |
| Monolithic system prompt | Stuffing everything into one file (like CLAUDE.md) doesn't scale | Progressive context injection via compiler |
| Platform-specific logic in core | Coupling kernel to Claude/Cursor/etc. makes it brittle | Adapter pattern with clean interfaces |
| Automatic code generation without gates | "Just let the agent code" without verification is how bugs ship | Always gate through evaluation framework |
| Opinionated language/framework choices | Forcing TypeScript or React opinions on users | Stay language-agnostic in specs; let users define their own |
| Real-time collaboration features | Multi-user real-time editing is a different product | Focus on async multi-agent, not multi-human |
| Billing/metering/usage tracking | SaaS concerns that don't belong in an open-source kernel | Leave to deployment layer |
| Model-specific optimizations | Coupling to GPT-4/Claude/Gemini internals is fragile | Model-agnostic adapter interface |
| Workflow rigidity | Forcing Plan-Execute-Finish on every task regardless of complexity | Allow workflow customization and escape hatches |

## Feature Dependencies

```
Event Sourcing Kernel
  ├── Deterministic Replay (requires event journal)
  ├── Dehydration/Hydration (requires serializable state)
  ├── Observability (requires structured events)
  └── Checkpoint/Resume (requires snapshot store)

Policy Engine
  ├── Approval Ledger (requires policy decisions)
  ├── Risk Tiers (requires capability classification)
  └── Human-in-the-Loop (requires ask/deny decisions)

Platform Configurators
  ├── Hook Generation (requires platform knowledge)
  ├── Skill Deployment (requires platform skill format)
  ├── Template Hashing (requires generated file tracking)
  └── Migration System (requires version awareness)

Context Compiler
  ├── Token Budget Management (requires token counting)
  ├── Spec Injection (requires spec discovery)
  └── Progressive Loading (requires priority ranking)

Task System
  ├── Workflow State Machine (requires task status)
  ├── Sub-agent Dispatch (requires task context)
  ├── Session-scoped Pointers (requires identity)
  └── Task Hierarchy (requires parent/child links)

Orchestration
  ├── Pipeline DAG (requires dependency resolution)
  ├── Parallel Execution (requires worktree isolation)
  ├── Issue Tracker Integration (requires external service adapters)
  └── Fleet Management (requires agent registry)
```

## MVP Recommendation (Next Milestone)

**Priority 1 — Platform parity (table stakes gap):**
1. Expand from 3 to 14+ platform configurators (Kiro, Gemini, Copilot, Windsurf, OpenCode, Pi, Qoder, CodeBuddy, Droid, Antigravity, Kilo)
2. Per-platform hook/skill/agent generation matching Trellis quality
3. Template-based config with hash-based staleness detection (already exists, needs platform coverage)

**Priority 2 — Workflow UX (Trellis strengths to match):**
4. Per-turn workflow breadcrumb injection (equivalent to Trellis's `[workflow-state:*]` blocks)
5. Guided brainstorm/planning skill (equivalent to trellis-brainstorm)
6. Knowledge capture workflow (equivalent to trellis-update-spec)
7. Break-loop / debug retrospective capability

**Priority 3 — Unique differentiators to polish:**
8. Issue-tracker-as-control-plane (Symphony-style: Linear/GitHub poll -> auto-spawn agents)
9. Fleet management dashboard via HTTP API
10. Deterministic replay CLI command (`reins replay <run-id>`)

**Defer:**
- GUI/dashboard: let the API mature first
- Cloud deployment: local-first is the right call for now
- Additional external integrations beyond GitHub/Linear/Jira/Slack: wait for demand

## Complexity Budget

| Priority | Feature Set | Estimated Effort | Risk |
|----------|-------------|-----------------|------|
| P1 | Platform parity (11 new configurators) | 2-3 weeks | Low (pattern established) |
| P1 | Hook/skill generation per platform | 1-2 weeks | Med (platform quirks) |
| P2 | Workflow breadcrumb system | 1 week | Low |
| P2 | Brainstorm/planning skill | 1 week | Low |
| P2 | Knowledge capture workflow | 3-4 days | Low |
| P2 | Break-loop capability | 3-4 days | Low |
| P3 | Issue-tracker control plane | 2-3 weeks | High (async complexity) |
| P3 | Fleet management API | 1-2 weeks | Med |
| P3 | Replay CLI command | 1 week | Low (kernel supports it) |

## Sources

- Trellis v0.5 source code (local `.memo/Trellis/`)
- [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/) — principles of agent-first development
- [OpenAI Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/) — issue-tracker-as-control-plane pattern
- [Anthropic Harness Design](https://www.anthropic.com/engineering/harness-design-long-running-apps) — long-running agent patterns
- [Martin Fowler: Harness Engineering](https://martinfowler.com/articles/harness-engineering.html) — confidence and verification
- [Stripe Minions Blueprint Architecture](https://www.mindstudio.ai/blog/stripe-minions-blueprint-architecture-deterministic-agentic-nodes) — deterministic + agentic node pattern
- [LangChain DeepAgents Harness](https://docs.langchain.com/oss/python/deepagents/harness) — planning, filesystem, permissions, subagents, context management
- [Harness Engineering: 5 Rules](https://akillness.github.io/posts/harness-engineering/) — OpenAI's constraint-based approach
- [Augment: Harness Engineering for AI Coding Agents](https://www.augmentcode.com/guides/harness-engineering-ai-coding-agents) — constraints that ship reliable code
