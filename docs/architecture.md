# Reins Architecture Guide

## Overview

Reins is an event-sourced agent control kernel for AI coding agents. It provides
deterministic, auditable agent orchestration where every action is event-sourced,
policy-gated, and traceable.

Where template-based harnesses offer static configuration, Reins provides a kernel
with formal guarantees: append-only event journals, pure reducer state transitions,
capability-based policy enforcement, and handle-based sandboxed execution.

## Layer Architecture

```
CLI / API (user-facing interfaces)
   |
Orchestration (multi-agent coordination, pipelines)
   |
Context (token-budgeted spec assembly)
   |
Policy Engine (capability evaluation, risk tiers)
   |
Execution (sandboxed adapters: shell, fs, git, MCP)
   |
Kernel (events, reducer, snapshots, routing)
```

Each layer depends only on layers below it. The kernel has zero external
dependencies beyond Python stdlib and pydantic.

## Kernel Layer

Location: `src/reins/kernel/`

The kernel provides event sourcing primitives and the state machine.

- **EventEnvelope** (`event/envelope.py`): Immutable event record with SHA-256
  checksum, trace_id, causation chain, actor, and monotonic sequence number.
- **EventJournal** (`event/journal.py`): Append-only JSONL persistence. Supports
  single-file and directory modes with rotation and compaction.
- **Reducer** (`reducer/`): Pure state transition functions. No I/O, no side
  effects. Given a state and an event, produces the next state deterministically.
- **RunState** (`reducer/state.py`): Mutable state rebuilt by replaying events
  through the reducer. Tracks grants, handles, pending repairs, and run status.
- **SnapshotStore** (`snapshot/store.py`): Point-in-time state capture for fast
  recovery without full replay.
- **Router** (`routing/`): Routes intents to appropriate handlers based on event
  type and current state.
- **Orchestrator** (`orchestrator.py`): Full run lifecycle supervisor loop that
  ties kernel primitives together.

## Policy Layer

Location: `src/reins/policy/`

The policy layer evaluates capability requests against risk tiers and rules.

- **PolicyEngine** (`engine.py`): Core evaluation logic. Receives a capability
  request and returns a PolicyDecision (allow, ask, deny, or route_remote).
- **Risk Tiers**: Four levels (low, medium, high, critical) that determine
  whether an action can proceed automatically or requires approval.
- **Rules** (`rules.py`): Declarative rule definitions that match capability
  patterns to risk assessments.
- **Constraints** (`constraints.py`): Boundary conditions that restrict what
  granted capabilities can do (path restrictions, command allowlists).
- **Approval** (`approval/`): Workflow for human-in-the-loop approval of
  high-risk actions. Maintains an audit ledger of all decisions.

## Execution Layer

Location: `src/reins/execution/`

The execution layer dispatches trusted commands to sandboxed adapters.

- **Adapter ABC** (`adapter.py`): Abstract base class defining the handle-based
  execution lifecycle: open, exec, freeze, thaw.
- **Adapters** (`adapters/`): Concrete implementations for shell commands,
  filesystem operations, git operations, and MCP tool calls.
- **ExecutionDispatcher** (`dispatcher.py`): Routes command envelopes to the
  appropriate adapter based on command type.
- **ParallelExecutor** (`parallel_executor.py`): Manages concurrent execution
  across multiple adapters with resource limits.
- **MCP Transport** (`mcp/`): Client for Model Context Protocol servers,
  enabling tool use across process boundaries.
- **Handle Lifecycle**: Each execution session follows open (acquire resources)
  -> exec (run command) -> freeze (serialize state) -> thaw (restore state).

## Context Layer

Location: `src/reins/context/`

The context layer assembles token-budgeted context from specs for agent sessions.

- **ContextCompilerV2** (`compiler_v2.py`): Spec-based context assembly with
  three tiers of priority.
- **Token Budget** (`token_budget.py`): Allocates token capacity across context
  tiers to stay within model limits.
- **Three Tiers**:
  - `standing_law`: Always-present rules and constraints
  - `task_contract`: Current task requirements and acceptance criteria
  - `spec_shards`: Relevant specification fragments selected by applicability
- **Spec Projection** (`spec_projection.py`): Projects specs into context based
  on task relevance and applicability scoring.
- **Breadcrumb Injection** (`breadcrumb_injection.py`): Injects workflow state
  markers so agents know where they are in a multi-step process.

## Orchestration Layer

Location: `src/reins/orchestration/`

The orchestration layer coordinates multi-agent workflows and pipelines.

- **Orchestrator** (`orchestrator.py`): High-level workflow coordinator that
  manages run lifecycle: create, route, execute, evaluate.
- **Pipeline** (`pipeline.py`): Declarative multi-stage workflow DAG defined in
  YAML with stages, dependencies, and agent type assignments.
- **SubagentManager** (`subagent_manager.py`): Manages parallel agent execution,
  resource allocation, and result aggregation.
- **Coordinator** (`coordinator.py`): Handles inter-agent communication and
  synchronization points in complex workflows.
- **Workflow** (`workflow.py`): Workflow definition and execution engine.
- **MCP Session** (`mcp_session.py`): Manages MCP server sessions for
  tool-using agents.

## Task System

Location: `src/reins/task/`

The task system provides CQRS-based task lifecycle management.

- **TaskManager** (`manager.py`): Command side. Creates, starts, completes, and
  archives tasks. Each state transition emits an event.
- **TaskContextProjection** (`projection.py`): Query side. Maintains a read model
  of task state by applying events, enabling fast lookups without replay.
- **Lifecycle**: created -> started -> completed -> archived. Each transition is
  an event in the journal.

## Integration Layer

Location: `src/reins/integrations/`

The integration layer connects Reins to external services.

- **GitHub** (`github.py`): PR creation, status checks, comment sync.
- **Linear** (`linear.py`): Issue tracking bidirectional sync.
- **Slack** (`slack.py`): Notifications and approval requests via webhooks.
- **Jira** (`jira.py`): Issue tracking integration.
- **Triggers** (`triggers.py`): Event-driven trigger engine that maps external
  events to internal actions.
- **Webhooks** (`webhooks.py`): Inbound webhook parsing and validation.

## CLI Layer

Location: `src/reins/cli/`

The CLI provides the user-facing command-line interface.

- **Main** (`main.py`): Typer application with subcommands for task, spec,
  workspace, worktree, and pipeline management.
- **Commands** (`commands/`): Individual command implementations organized by
  domain (init, task, spec, workspace, worktree, pipeline, update).
- **Utils** (`utils.py`): Shared CLI utilities including repo discovery, config
  loading, event emission, and output formatting.

## API Layer

Location: `src/reins/api/`

The API provides an HTTP interface for programmatic access.

- **Server** (`server.py`): aiohttp-based HTTP server bound to localhost by
  default (requires `--expose-network` for non-local binding).
- **Routes** (`routes.py`): REST endpoints for run management, event queries,
  and state inspection.
- **Command Routes** (`command_routes.py`): Endpoints for dispatching commands
  to running agent sessions.

## Data Flow

### How an Agent Action Flows Through the System

1. **Intent**: An agent (via CLI or API) expresses an intent to perform an action.
2. **Policy Check**: The policy engine evaluates the capability request against
   risk tiers and rules. High-risk actions require approval.
3. **Grant**: If approved, a grant is issued and recorded as an event.
4. **Dispatch**: The execution dispatcher routes the command to the appropriate
   adapter (shell, fs, git, MCP).
5. **Execution**: The adapter executes the command in a sandboxed environment
   and produces an Observation (exit code, stdout, stderr).
6. **Event**: The result is recorded as an event in the journal.
7. **Reduce**: The reducer applies the event to produce the next state.
8. **Snapshot**: Periodically, state is snapshotted for fast recovery.

### Event Sourcing Guarantees

- **Append-only**: Events are never modified or deleted from the journal.
- **Checksummed**: Each event includes a SHA-256 checksum for integrity.
- **Ordered**: Events have monotonic sequence numbers within a run.
- **Causal**: Events carry causation_id linking effects to their causes.
- **Replayable**: Any state can be reconstructed by replaying events from the
  beginning (or from a snapshot).

### Replay and Time-Travel

The journal supports time-travel debugging: replay events up to any point to
reconstruct historical state. Combined with snapshots, this enables efficient
recovery without replaying the entire history.

## Key Design Decisions

### Why Event Sourcing

- **Auditability**: Complete history of every action and decision.
- **Replay**: Reconstruct any past state for debugging or analysis.
- **Determinism**: Same events always produce the same state.
- **Decoupling**: Writers append events; readers project views independently.

### Why Pure Reducers

- **Testability**: State transitions can be tested without I/O or mocks.
- **Determinism**: Given the same state and event, output is always identical.
- **Composability**: Reducers can be composed and layered.

### Why Capability-Based Policy

- **Least Privilege**: Agents only get capabilities they need.
- **Graduated Trust**: Risk tiers allow automatic approval for safe actions.
- **Audit Trail**: Every grant and denial is recorded.

### Why Handle-Based Execution

- **Sandboxing**: Each execution context is isolated.
- **Lifecycle Management**: Resources are explicitly acquired and released.
- **Durability**: Handles can be frozen and thawed across process restarts.

## Contributing

### Adding a New Adapter

1. Create a new module in `src/reins/execution/adapters/`.
2. Implement the `Adapter` ABC from `src/reins/execution/adapter.py`.
3. Register the adapter in the `ExecutionDispatcher`.
4. Add tests in `tests/` covering open, exec, freeze, and thaw.

### Adding a New CLI Command

1. Create a command module in `src/reins/cli/commands/`.
2. Define a typer command function with appropriate parameters.
3. Register it in `src/reins/cli/main.py`.
4. Add integration tests in `tests/integration/`.

### Adding a New Integration

1. Create a client module in `src/reins/integrations/`.
2. Implement the HTTP client using httpx with TLS validation.
3. Add trigger mappings in `triggers.py` if needed.
4. Add tests with mocked HTTP responses.

### Testing Conventions

- Unit tests: `tests/test_*.py` or `tests/unit/test_*.py`
- Integration tests: `tests/integration/test_*.py`
- Use pytest with pytest-asyncio for async tests
- Mock external I/O; test reducers and policy logic purely
- Run: `.venv/bin/pytest tests/ -x -q`
