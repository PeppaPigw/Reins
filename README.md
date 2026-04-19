# Reins

[简体中文](README.zh-CN.md)

> Basic rules with enough freedom.

Reins is a Python toolkit for adding structured task, spec, worktree, and pipeline management to AI-assisted coding repositories. In the current codebase, the primary interface is the `reins` CLI, and the working control plane lives under `.reins/`.

Instead of asking agents to rediscover project state on every run, Reins writes that state down as repository artifacts:

- task metadata and PRDs under `.reins/tasks/`
- layered guidance under `.reins/spec/`
- seeded JSONL context files for `implement`, `check`, and `debug`
- tracked git worktrees for parallel lanes
- per-developer workspace journals and reports
- event-backed pipeline state and audit history

## What Reins does today

The repository currently ships these capabilities:

- a Typer-based CLI for bootstrapping and operating a Reins-enabled repo
- first-class platform configurators for Codex, Claude Code, and Cursor
- task lifecycle commands that export task artifacts to the filesystem
- spec initialization, fetch, update, checklist, and validation workflows
- package-aware context seeding from PRDs and spec layers
- tracked git worktree management for parallel agent execution
- developer/workspace tracking with activity stats and cleanup commands
- YAML-defined multi-stage pipelines stored under `.reins/pipelines/`
- an optional `aiohttp` API for lower-level run orchestration

## Install Reins

Reins requires Python 3.11 or newer.

Install it in editable mode:

```bash
pip install -e ".[dev]"
```

This exposes the `reins` command from `pyproject.toml`:

```bash
reins --help
```

## Quick start

Initialize a repository, register the active developer, create a task, seed context, and run a pipeline:

```bash
reins init --platform codex --project-type backend
reins developer init peppa
reins spec init --package cli

reins task create "Implement JWT auth" \
  --type backend \
  --priority P0 \
  --acceptance "JWT tokens are issued after login" \
  --acceptance "Protected routes reject invalid tokens"

reins task list
reins task init-context <task-id> backend
reins task start <task-id>

reins spec checklist --task <task-id> --validate
reins worktree create feature-jwt --task <task-id>
reins pipeline list
reins pipeline run standard --task .reins/tasks/<task-id>
reins status --verbose
```

If you want shell completion:

```bash
reins completion zsh > ~/.reins-completion.zsh
source ~/.reins-completion.zsh
```

## What `reins init` creates

After initialization, Reins scaffolds the repository around a `.reins/` directory:

```text
.reins/
  journal.jsonl
  .current-task
  tasks/
  spec/
  workspace/
```

As you use the CLI, Reins adds more derived artifacts:

```text
.reins/tasks/<task-id>/
  task.json
  prd.md
  implement.jsonl
  check.jsonl
  debug.jsonl
  pipeline-state.json

.reins/pipelines/
  debug.yaml
  research-heavy.yaml
  standard.yaml
  test-driven.yaml
```

The important detail is that these files are meant to be read by people and tooling alike. Reins is not only storing internal state. It is exporting a working surface that agents, hooks, and humans can inspect directly.

## Command overview

### `reins init`

Bootstraps `.reins/`, detects or accepts a target platform, applies platform templates, and migrates the standard spec layout.

Useful options:

- `--platform`: explicit platform override such as `codex`, `claude`, or `cursor`
- `--project-type`: set `frontend`, `backend`, or `fullstack`
- `--developer`: seed the developer identity used during template rendering
- `--package`: scaffold package-local spec guidance for monorepos

### `reins status`

Shows the current task, task status, active agents, developer identity, workspace journal count, git changes, and recent journal activity. Use `--verbose` for expanded details.

### `reins developer ...`

Manages the active developer identity stored in `.reins/.developer`.

Useful commands:

- `reins developer init`
- `reins developer show`
- `reins developer workspace-info`

### `reins workspace ...`

Inspects and maintains per-developer workspace data.

Useful commands:

- `reins workspace init`
- `reins workspace list`
- `reins workspace stats`
- `reins workspace cleanup`
- `reins workspace report`

### `reins task ...`

Creates, exports, and advances task artifacts.

Useful commands:

- `reins task create`
- `reins task list`
- `reins task show`
- `reins task start`
- `reins task finish`
- `reins task archive`
- `reins task init-context`
- `reins task add-context`

When you run `reins task init-context <task-id> <backend|frontend|fullstack>`, Reins seeds:

- `implement.jsonl`
- `check.jsonl`
- `debug.jsonl`

Those files are built from the task PRD plus the relevant spec layers under `.reins/spec/`.

### `reins spec ...`

Manages layered repo guidance.

Useful commands:

- `reins spec init`
- `reins spec update`
- `reins spec fetch`
- `reins spec list`
- `reins spec validate`
- `reins spec add-layer`
- `reins spec checklist`

The default global layers are:

- `backend`
- `frontend`
- `unit-test`
- `integration-test`
- `guides`

For package-based repos, Reins can also create package-local layers under `.reins/spec/<package>/...`.

### `reins worktree ...`

Creates and tracks git worktrees tied to tasks or agent lanes.

Useful commands:

- `reins worktree create`
- `reins worktree list`
- `reins worktree verify`
- `reins worktree cleanup`
- `reins worktree cleanup-orphans`
- `reins worktree prune`

### `reins journal ...`

Inspects the event journal behind the CLI workflows.

Useful commands:

- `reins journal show`
- `reins journal replay`
- `reins journal export`
- `reins journal stats`

### `reins pipeline ...`

Runs named, YAML-defined workflows against task directories.

Useful commands:

- `reins pipeline list`
- `reins pipeline run`
- `reins pipeline status`
- `reins pipeline cancel`

## Built-in pipelines

The repository currently includes four pipeline definitions under `.reins/pipelines/`:

| Pipeline | Purpose |
| --- | --- |
| `standard` | Research, implementation, checking, and verification |
| `research-heavy` | Parallel research first, then implementation and verification |
| `test-driven` | Define verification targets before implementation |
| `debug` | Diagnose a failure, apply a fix, and verify it |

Pipelines are declarative YAML files. Each stage defines:

- a stage type such as `research`, `implement`, `check`, `verify`, or `debug`
- an `agent_type`
- a prompt template
- dependency order
- retry policy
- optional context files to inject

## How spec and context layering works

Context resolution is package-aware and layer-aware.

In the current implementation:

- package-local spec layers are resolved before global layers
- task type controls which layers are selected
- `guides` are appended after task-type layers
- duplicate spec sources are filtered before context compilation

That means you can keep organization-wide guidance in global layers while still overriding behavior for a single package when needed.

## Platform support

Reins contains a broader platform registry, but the repo currently ships built-in template/configuration support for:

- Codex
- Claude Code
- Cursor

These live under `src/reins/platform/templates/` and are applied during `reins init`.

## Optional HTTP API

If you need a lower-level integration surface, Reins also includes an `aiohttp` server:

```bash
python -m reins.api.server --port 8000 --state-dir .reins_state
```

Key routes:

- `POST /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/timeline`
- `POST /runs/{id}/commands`
- `POST /runs/{id}/approve`
- `POST /runs/{id}/reject`
- `POST /runs/{id}/abort`
- `POST /runs/{id}/resume`

This API is useful when you want to drive the lower-level run/orchestrator flow directly instead of going through the CLI.

## Repository docs

For more detail, start with:

- `docs/cli-reference.md`
- `docs/spec-schema.md`
- `docs/PARALLEL-EXECUTION-STRATEGY.md`
- `docs/ROADMAP-DETAILED.md`

## Develop on Reins

Run the standard checks:

```bash
ruff check src tests
mypy src
pytest
```

If you only want a fast CLI sanity pass while iterating:

```bash
PYTHONPATH=src python -m reins.cli.main --help
PYTHONPATH=src python -m reins.cli.main pipeline list
```

## Source layout

The current source tree is organized roughly like this:

- `src/reins/cli/`: user-facing CLI entrypoints and command groups
- `src/reins/platform/`: platform detection, templates, and configurators
- `src/reins/task/`: task metadata, projections, and JSONL context storage
- `src/reins/context/`: spec resolution and context compilation
- `src/reins/workspace/`: developer workspace state, stats, and reporting
- `src/reins/isolation/`: tracked git worktree management
- `src/reins/orchestration/`: pipeline execution and stage coordination
- `src/reins/kernel/`, `src/reins/policy/`, `src/reins/execution/`: lower-level event, policy, and execution primitives
- `src/reins/api/`: optional HTTP API surface

## Contributing

When changing the project:

1. Update code and tests together.
2. Run lint, type checks, and relevant tests.
3. Keep command examples aligned with `reins --help`.
4. Prefer documenting the CLI and repository artifacts that actually exist over aspirational architecture notes.
