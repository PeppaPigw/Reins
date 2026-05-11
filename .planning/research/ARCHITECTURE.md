# Architecture Patterns

**Domain:** AI coding agent control kernel
**Researched:** 2026-05-11
**Confidence:** HIGH (based on existing codebase analysis + industry patterns)

## Recommended Architecture: Event-Sourced Agent Control Kernel

Reins implements a **kernel architecture** — a formal control plane that mediates all agent actions through event-sourced state, policy evaluation, and sandboxed execution. This is structurally superior to Trellis's template-based approach because it provides runtime guarantees that static file generation cannot.

The architecture follows a layered kernel pattern with strict dependency direction (inner layers know nothing about outer layers):

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI / API (Entry)                         │
├─────────────────────────────────────────────────────────────────┤
│                    Orchestration Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  Coordinator │  │   Pipeline   │  │   SubagentManager     │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                    RunOrchestrator (Supervisor Loop)             │
│  intake → route → [plan] → execute → evaluate → decide         │
├──────────┬──────────┬──────────────┬────────────────────────────┤
│  Policy  │ Context  │  Execution   │  Evaluation                │
│  Engine  │ Compiler │  Dispatcher  │  Runner                    │
├──────────┴──────────┴──────────────┴────────────────────────────┤
│                    Kernel (Pure Domain)                          │
│  EventJournal │ Reducer │ RunState │ Router │ SnapshotStore     │
└─────────────────────────────────────────────────────────────────┘
```

### Component Boundaries

| Component | Responsibility | Communicates With | Boundary Type |
|-----------|---------------|-------------------|---------------|
| **Kernel** | Event sourcing primitives, state machine, pure reducers | Nothing (pure domain) | Hard boundary — no I/O, no dependencies |
| **Policy Engine** | Evaluate capabilities against risk tiers, rules, constraints | Kernel types only | Async interface, audit sink |
| **Execution Dispatcher** | Route commands to sandboxed adapters via handles | Kernel types, Adapter ABC | Handle-based session isolation |
| **Context Compiler** | Token-budgeted context assembly from specs | Kernel types, SpecProjection | Pure computation, no side effects |
| **RunOrchestrator** | Supervisor loop for single run lifecycle | All domain layers | Coordination boundary — no model calls |
| **Orchestration** | Multi-agent coordination, pipelines, DAG execution | RunOrchestrator, Policy, Journal | Workflow boundary |
| **Platform** | Generate platform-specific configs (Claude, Cursor, Codex) | Config, templates | File generation boundary |
| **Workspace** | Developer journals, sessions, activity tracking | Kernel journal | Read-only projection |
| **Isolation** | Git worktree management for parallel execution | Kernel journal, git subprocess | Process boundary |
| **Evaluation** | Lint, spec, test evaluators with failure classification | Kernel types | Pure assessment, no mutation |

### Data Flow

**Primary flow — Command Processing Pipeline:**

```
External Model Adapter
        │
        ▼ CommandProposal
┌─RunOrchestrator──────────────────────────────────────────┐
│  1. Materialize → CommandEnvelope (with risk tier)        │
│  2. Validate (required args, type checks)                │
│  3. Build EffectDescriptor (capability, resource, intent)│
│  4. PolicyEngine.evaluate() → allow/ask/deny/route       │
│  5. If allowed: Dispatcher.dispatch() → Observation      │
│  6. EventBuilder.emit() → EventJournal.append()          │
│  7. reduce(state, event) → new RunState                  │
│  8. EvaluationRunner.check() → pass/fail                 │
│  9. If fail: classify → repair loop                      │
└──────────────────────────────────────────────────────────┘
```

**Secondary flow — Context Injection:**

```
SpecProjection (spec registry)
        │
        ▼ ResolvedSpecs
ContextCompilerV2.seed_context()
        │
        ▼ ContextAssemblyManifest
  ┌─────────────────────────────┐
  │ standing_law (always-on)    │
  │ task_contract (task-scoped) │
  │ spec_shards (on-demand)     │
  └─────────────────────────────┘
        │
        ▼ Injected into agent session
```

**Tertiary flow — Multi-Agent Orchestration:**

```
Pipeline (YAML-defined DAG)
        │
        ▼ PipelineStages
PipelineCoordinator
        │
        ├─▶ Stage A (no deps) ──▶ SubagentManager.spawn()
        │                              │
        │                              ▼ Child RunOrchestrator
        │                              (own RunState, scoped grants)
        │
        ├─▶ Stage B (depends A) ──▶ waits for A completion
        │
        └─▶ Stage C (no deps) ──▶ parallel with A
```

## Patterns to Follow

### Pattern 1: Pure Reducer (Event Sourcing Core)

**What:** State transitions are pure functions: `reduce(state, event) -> new_state`. No I/O, no side effects, no exceptions for control flow.

**When:** Always — this is the kernel's invariant.

**Why this matters vs Trellis:** Trellis mutates files on disk. Reins can replay any run from its event log, reconstruct state at any point in time, and prove what happened. This is the single most important architectural advantage.

```python
def reduce(state: RunState, event: EventEnvelope) -> RunState:
    """Pure reducer. Returns new state from current state + event. No I/O."""
    if event.type == "run.started":
        return replace(state, status=RunStatus.routing)
    if event.type == "policy.grant_issued":
        active_grants = list(state.active_grants)
        active_grants.append(_grant_from_payload(event.payload))
        return replace(state, active_grants=active_grants)
    # ... deterministic for every event type
    return replace(state)
```

### Pattern 2: Handle-Based Execution Isolation

**What:** Every adapter interaction goes through a stateful Handle with open/exec/freeze/thaw/close lifecycle. Handles are the unit of isolation.

**When:** Any side-effecting operation (file writes, git operations, shell commands, MCP calls).

**Why this matters:** Handles enable dehydration (serialize running state), crash recovery (thaw frozen handles), and audit (every handle operation is an event).

```python
class Adapter(ABC):
    async def open(self, spec: dict) -> Handle: ...
    async def exec(self, handle: Handle, command: dict) -> Observation: ...
    async def freeze(self, handle: Handle) -> dict: ...
    async def thaw(self, frozen: dict) -> Handle: ...
```

### Pattern 3: Capability-Based Policy Gating

**What:** Every command is evaluated against a policy engine before execution. Risk tiers (T0-T4) determine auto-allow, ask-human, or deny. Rules and constraints can override defaults.

**When:** Every command proposal, without exception.

**Why this matters:** Trellis has no runtime policy enforcement. Reins can prevent destructive operations, require human approval for high-risk actions, and audit every decision.

### Pattern 4: CQRS Task Lifecycle

**What:** Commands (create, start, complete, archive) go through the event journal. Queries (list tasks, get context) read from projections rebuilt from events.

**When:** All task state management.

**Why this matters:** Projections can be rebuilt from events. Multiple read models can coexist (TaskContextProjection, WorkspaceStats, etc.) without coupling.

### Pattern 5: Declarative Pipeline DAG

**What:** Multi-stage workflows defined in YAML with dependency tracking. Stages execute in parallel when dependencies allow.

**When:** Complex multi-agent workflows (research → implement → verify).

```yaml
stages:
  - name: research
    type: research
    agent_type: researcher
    depends_on: []
  - name: implement
    type: implement
    agent_type: coder
    depends_on: [research]
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Model Calls Inside the Kernel

**What:** The RunOrchestrator calling LLM APIs directly.
**Why bad:** Couples the kernel to specific model providers. Makes testing require API mocking. Breaks the "trusted pipeline" boundary.
**Instead:** The orchestrator receives CommandProposals from an external model adapter. The kernel never calls the model.

### Anti-Pattern 2: Mutable State Without Events

**What:** Changing RunState fields directly without emitting an event.
**Why bad:** Breaks replay, breaks time-travel, breaks audit trail. The event log becomes inconsistent with actual state.
**Instead:** Every state change must flow through: emit event → journal append → reduce → new state.

### Anti-Pattern 3: Ambient Authority in Execution

**What:** Adapters that can do anything without policy checks.
**Why bad:** No audit trail, no risk assessment, no human-in-the-loop for dangerous operations.
**Instead:** Every execution goes through PolicyEngine.evaluate() first. The dispatcher only receives pre-approved commands.

### Anti-Pattern 4: Tight Coupling Between Orchestration and Platform

**What:** Pipeline logic that assumes specific platform configurations.
**Why bad:** Adding a new platform (Gemini, Windsurf) shouldn't require changing orchestration code.
**Instead:** Platform configurators are leaf nodes. They consume kernel output but never influence kernel behavior.

## Where Reins Architecture Is Already Superior

| Dimension | Reins | Trellis | Advantage |
|-----------|-------|---------|-----------|
| **State management** | Event-sourced with pure reducers | File mutation on disk | Deterministic replay, time-travel, crash recovery |
| **Policy enforcement** | Runtime capability evaluation with risk tiers | None (trust the agent) | Prevents destructive operations, audit trail |
| **Execution isolation** | Handle-based adapters with freeze/thaw | Direct file writes | Dehydration, resumability, sandboxing |
| **Multi-agent coordination** | Pipeline DAG with dependency tracking | None (single-agent) | Parallel execution, workflow composition |
| **Observability** | Structured events with trace IDs, causation chains | Log files | Full causal tracing, replay debugging |
| **Context management** | Token-budgeted compilation with spec projection | Static file concatenation | Adaptive context, audit of what was injected |
| **Failure handling** | Typed failure classification with repair routing | Crash and retry | Intelligent recovery, repair loops |

## Where Reins Architecture Needs Work

| Gap | Current State | Required State | Priority |
|-----|---------------|----------------|----------|
| **Platform parity** | 3 configurators (Claude, Cursor, Codex) | 14+ matching Trellis | HIGH — table stakes |
| **Migration system** | Basic module exists | Version-tracked with rollback, template hashing | HIGH — operational necessity |
| **Event schema evolution** | No versioning on event payloads | Schema registry with backward compatibility | MEDIUM — needed before v1.0 |
| **Projection rebuild performance** | Full replay from journal | Snapshot-based fast rebuild, incremental projections | MEDIUM — matters at scale |
| **Plugin system** | Adapter ABC exists | Formal plugin registry with discovery, versioning | MEDIUM — extensibility |
| **Distributed execution** | Local-only parallel execution | Remote agent coordination (A2A routing exists but untested) | LOW — future capability |
| **Backpressure** | No flow control on command processing | Rate limiting, queue depth monitoring | LOW — matters at high throughput |

## Suggested Build Order (Dependencies)

The architecture has clear dependency layers that dictate build order:

```
Phase 1: Kernel Hardening (no external deps)
  ├── Event schema versioning
  ├── Snapshot-based projection rebuild
  └── Reducer property-based testing

Phase 2: Policy & Security (depends on kernel)
  ├── Policy rule DSL improvements
  ├── Constraint composition
  └── Audit sink implementations (file, structured log)

Phase 3: Execution & Adapters (depends on kernel + policy)
  ├── Plugin registry for adapters
  ├── Handle lifecycle improvements (TTL, cleanup)
  └── MCP transport hardening

Phase 4: Context & Evaluation (depends on kernel)
  ├── Incremental context enrichment
  ├── Spec applicability engine
  └── Evaluation framework expansion

Phase 5: Platform Parity (depends on execution + context)
  ├── 11 additional configurators
  ├── Template hashing for staleness detection
  └── Migration system with rollback

Phase 6: Orchestration & Multi-Agent (depends on all above)
  ├── Pipeline composition (pipelines calling pipelines)
  ├── Cross-run correlation
  └── Distributed subagent coordination
```

**Rationale:** Inner layers must be solid before outer layers can be reliable. Kernel hardening first because every other layer depends on event integrity. Platform parity is Phase 5 because it's leaf-node work that doesn't block other development.

## Scalability Considerations

| Concern | At 10 runs/day | At 1K runs/day | At 100K runs/day |
|---------|----------------|----------------|------------------|
| **Journal storage** | JSONL files per run | JSONL with compaction | Event store (append-only DB) |
| **Snapshot frequency** | Every N events | Adaptive (based on replay cost) | Continuous snapshotting |
| **Policy evaluation** | In-process sync | In-process with caching | Dedicated policy service |
| **Parallel execution** | asyncio tasks | Worker pool with semaphore | Distributed task queue |
| **Context compilation** | On-demand | Cached with invalidation | Pre-computed projections |

## Structural Advantages Over Template-Based Architecture

The kernel architecture provides five structural advantages that a template-based system (Trellis) cannot replicate without a fundamental rewrite:

1. **Temporal queries** — "What was the agent doing at 14:32?" is a simple replay. Templates have no history.

2. **Formal safety guarantees** — Policy evaluation is mandatory, not optional. Templates can be bypassed by editing files.

3. **Composable workflows** — Pipelines, subagents, and parallel execution are first-class. Templates generate static files.

4. **Crash recovery** — Dehydrate/hydrate with frozen handles means runs survive process death. Templates have no run concept.

5. **Extensibility without modification** — New adapters, evaluators, and policy rules plug in without changing the kernel. Templates require modifying the generator.

## Sources

- Codebase analysis: `src/reins/kernel/`, `src/reins/policy/`, `src/reins/execution/`, `src/reins/orchestration/`
- [Agent Control Plane concept — Activant Capital](https://activantcapital.com/research/the-agent-control-plane)
- [From Guardrails to Operating Model: The Agent Control Plane](https://khaledzaky.com/blog/from-guardrails-to-operating-model-the-agent-control-plane)
- [Event Sourcing for Agents: Log-Based Architecture](https://understandingdata.com/posts/event-sourcing-agents/)
- [Agent Observability for AI Coding — Augment](https://www.augmentcode.com/guides/agent-observability-for-ai-coding)
- [Capability-Sealed Secret Mediation for Secure Agent Execution](https://arxiv.org/html/2604.16762v1)
- [MicroKernel Multi-Agent System Framework](https://arxiv.org/html/2512.01610)
- [Four Design Patterns for Event-Driven Multi-Agent Systems — Confluent](https://www.confluent.io/blog/event-driven-multi-agent-systems/)
- [Securing Agent Orchestration: Patterns and Controls](http://www.arunbaby.com/ai-security/0021-securing-agent-orchestration-patterns-and-controls/)
- [AI Agent Architecture Patterns — Stack AI](https://www.stack-ai.com/insights/ai-agent-architecture-patterns-sequential-parallel-and-hierarchical-workflows)

---

*Architecture analysis: 2026-05-11*
