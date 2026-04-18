# Reins Backend Index

Reins is an event-sourced agent control kernel. Backend code is organized around
trusted kernel planes, not request-response controller layers.

## Core Doctrine

- The model never commits canonical events. It emits proposals only.
- The journal is for replay, audit, and reduction, never for direct prompting.
- Read-only work routes to the fast path. Mutations, ambiguity, and approvals
  route to the deliberative path.
- Long waits become dehydrated checkpoints with explicit wake conditions.
- Skills are lazy capability modules loaded under policy envelopes.
- MCP is the default tool/resource bus. A2A is the remote-agent boundary.

## Read Order

1. [Project Doctrine](../guides/project-doctrine.md)
2. [Reins Invariants](../guides/reins-invariants.md)
3. [Directory Structure](./directory-structure.md)
4. [Quality Guidelines](./quality-guidelines.md)
5. [Database Guidelines](./database-guidelines.md)
6. [Error Handling](./error-handling.md)
7. [Logging Guidelines](./logging-guidelines.md)
8. [Worktree Patterns](./worktree-patterns.md) - Parallel agent execution
9. [Migration Patterns](./migration-patterns.md) - Template evolution

## Runtime Modules

- `src/reins/kernel/intent/envelope.py`
  Intake objects: `IntentEnvelope`, `CommandProposal`, `CommandEnvelope`.
- `src/reins/kernel/event/envelope.py`
  Canonical trusted event envelope and checksum logic.
- `src/reins/kernel/event/journal.py`
  Append-only JSONL journal for replayable event streams.
- `src/reins/kernel/reducer/state.py`
  Mutable runtime state and persisted snapshot view models.
- `src/reins/kernel/reducer/reducer.py`
  Pure reducer. No I/O, no subprocesses, no adapter calls.
- `src/reins/kernel/snapshot/store.py`
  JSON snapshot persistence.
- `src/reins/kernel/routing/router.py`
  Rules-first fast-vs-deliberative path routing.
- `src/reins/policy/capabilities.py`
  Canonical capability taxonomy and deterministic risk tiers.
- `src/reins/policy/engine.py`
  Policy decisions and grant issuance.
- `src/reins/execution/adapter.py`
  Handle-based adapter contract.
- `src/reins/execution/adapters/*.py`
  Local shell, filesystem, and git adapters.
- `src/reins/skill/catalog.py`
  Skill manifests and JSONL-backed registry.
- `src/reins/skill/resolver.py`
  Seven-stage skill resolution pipeline.
- `src/reins/memory/checkpoint.py`
  Checkpoint manifests and dehydration helpers.
- `src/reins/evaluation/classifier.py`
  Failure classification and retry policy.
- `src/reins/evaluation/evaluators/base.py`
  Evaluator base types.
- `src/reins/observability/trace.py`
  Structured JSON logging and trace IDs.
- `src/reins/isolation/worktree_manager.py`
  Git worktree lifecycle manager for parallel agent execution.
- `src/reins/isolation/worktree_config.py`
  YAML-based worktree configuration loader.
- `src/reins/isolation/agent_registry.py`
  Active agent tracking with JSON persistence.
- `src/reins/migration/engine.py`
  Declarative migration orchestration with rollback.
- `src/reins/migration/types.py`
  Migration manifest and operation types.
- `src/reins/migration/version.py`
  Semantic version comparison and filtering.

## Trusted Boundary

Trusted kernel code lives under `src/reins/`. The following are always
untrusted inputs and must be normalized before they influence state:

- model proposals
- human freeform input
- webhook payloads
- remote-agent outputs
- raw adapter stdout/stderr

Kernel code validates those inputs, evaluates policy, executes effects,
collects observations, builds events, commits to the journal, and reduces state.
