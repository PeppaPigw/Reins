# figure API

```bash
curl -s http://localhost:9235/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A cute cat sitting on a wooden table, soft natural lighting",
    "size": "1024x1024",
    "quality": "high",
    "output_format": "png",
    "output_compression": 100,
    "background": "opaque",
    "moderation": "high",
    "save_dir": "./generated_images",
    "filename": "my_cat.png",
    "output_path": null,
    "timeout_sec": 120,
    "max_attempts": 3
  }'
```

---

# 参数说明

## 必填参数

| 参数     | 类型   | 说明     |
| -------- | ------ | -------- |
| `prompt` | string | 图像描述 |

---

# 可选参数

## 图像生成参数

| 参数                 | 类型   | 默认值        | 可选值                                                         |
| -------------------- | ------ | ------------- | -------------------------------------------------------------- |
| `n`                  | int    | `1`           | `1-10`                                                         |
| `size`               | string | `"1024x1024"` | `1024x1024` `1536x1024` `1024x1536` `256x256` `512x512` `auto` |
| `quality`            | string | `"auto"`      | `low` `medium` `high` `auto`                                   |
| `output_format`      | string | `"png"`       | `png` `jpeg` `webp`                                            |
| `output_compression` | int    | `100`         | `0-100`（仅 jpeg/webp 生效）                                   |
| `background`         | string | `"auto"`      | `opaque` `auto`                                                |
| `moderation`         | string | `"auto"`      | `auto` `low`                                                   |
| `response_format`    | string | `"b64_json"`  | `b64_json` `url`                                               |
| `user`               | string | `null`        | 任意字符串                                                     |

| 参数          | 类型   | 默认值                 | 说明                       |
| ------------- | ------ | ---------------------- | -------------------------- |
| `save_dir`    | string | `"./generated_images"` | 保存目录                   |
| `filename`    | string | `null`                 | 文件名                     |
| `output_path` | string | `null`                 | 完整输出路径（优先级最高） |

## 请求控制参数

| 参数           | 类型 | 默认值 | 范围    |
| -------------- | ---- | ------ | ------- |
| `timeout_sec`  | int  | `120`  | `5-600` |
| `max_attempts` | int  | `3`    | `1-10`  |

# grok api

```
curl https://hub.oaifree.com/v1/chat/completions \
  -H "Authorization: Bearer ah-3e79d7867cfb0479f10df21d3aceb5ba120329a1fbb4b89d74f611070f0b41ba" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4.20-auto",
    "stream":false,
    "messages": [
      {
        "role": "user",
        "content": "helo"
      }
    ]
  }'
```

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Reins — Event-Sourced Agent Control Kernel**

Reins is a Python-native harness engineering framework that provides event-sourced agent orchestration, policy-driven execution, and progressive context injection for AI coding agents. It must surpass Trellis (the TypeScript reference at `.memo/Trellis`) in every measurable engineering dimension.

**Core Value:** **Deterministic, auditable agent control** — every agent action is event-sourced, policy-gated, and traceable. Where Trellis provides a template-based harness, Reins provides a kernel with formal guarantees.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python >=3.11 - All source code in `src/reins/`
- YAML - Configuration files (`.reins/config.yaml`, platform templates)
- Markdown - Specs, PRDs, documentation templates
## Runtime
- Python 3.11+
- asyncio-based (async/await throughout kernel, execution, orchestration layers)
- pip with hatchling build backend
- No lockfile detected (no `requirements.lock`, `poetry.lock`, or `uv.lock`)
## Frameworks
- pydantic >=2.0 - Data validation and serialization (`src/reins/kernel/`, `src/reins/config/`)
- aiohttp >=3.9 - HTTP API server (`src/reins/api/server.py`)
- typer >=0.9.0 - CLI framework (`src/reins/cli/main.py`)
- pytest >=8.0 - Test runner
- pytest-asyncio >=0.23 - Async test support
- hatchling - Build backend (`pyproject.toml`)
- ruff >=0.4 - Linting and formatting
- mypy >=1.10 - Static type checking
## Key Dependencies
- `pydantic` >=2.0 - Core data models, validation, serialization across all layers
- `aiohttp` >=3.9 - HTTP API server for the agent kernel
- `aiofiles` >=23.0 - Async file I/O for event journal (`src/reins/kernel/event/journal.py`)
- `structlog` >=24.0 - Structured logging (`src/reins/observability/trace.py`)
- `ulid-py` >=1.1 - Unique ID generation for events, sessions, traces
- `httpx` - Async HTTP client for MCP transport (`src/reins/execution/mcp/transport.py`)
- `PyYAML` >=6.0 - YAML config parsing (`src/reins/config/loader.py`)
- `typer` >=0.9.0 - CLI application framework
- `rich` >=13.7.0 - Terminal output formatting
- `tabulate` >=0.9.0 - Table rendering in CLI
## Configuration
- `REINS_HOST` - API server bind host (default: 0.0.0.0)
- `REINS_PORT` - API server bind port (default: 8000)
- `REINS_STATE_DIR` - Durable state directory (default: .reins_state)
- Integration env vars: `GITHUB_TOKEN`, `LINEAR_API_KEY`, `SLACK_WEBHOOK_URL`, `JIRA_*`
- `pyproject.toml` - Project metadata, dependencies, build config, ruff settings
- Ruff line-length: 100
## Platform Requirements
- Python 3.11+
- Git (used by worktree manager and git adapter via subprocess)
- Optional: MCP-compatible servers (Codex, GitNexus, ABCoder)
- Runs as CLI tool (`reins` entry point) or HTTP API server
- File-system based state (JSONL journals, JSON snapshots)
- No database required
## Entry Points
- `reins` → `src/reins/cli/main.py:main` (typer app)
- `python -m reins.api.server` → `src/reins/api/server.py:main` (aiohttp)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Use `snake_case.py` for all modules: `event_journal.py`, `agent_adapter.py`, `spec_registrar.py`
- Prefix private/internal modules with underscore: `_http.py`, `_hook_support.py`
- Test files: `test_<module_name>.py`
- Use `snake_case` for all functions and methods: `initialize_workspace()`, `dispatch()`, `compute_checksum()`
- Private helpers prefixed with underscore: `_grant_from_payload()`, `_resolve()`, `_handle_key()`
- Async functions use same naming (no `async_` prefix): `async def dispatch()`
- Use `snake_case`: `active_grants`, `run_id`, `open_handles`
- Constants use `UPPER_SNAKE_CASE`: `REDUCER_VERSION`, `CAPABILITY_RISK_TIERS`
- Use `PascalCase`: `RunState`, `EventEnvelope`, `PolicyEngine`, `GrantRef`
- Enums use `PascalCase` class with `snake_case` members: `RunStatus.waiting_approval`
- Dataclass names describe the entity: `PendingRepair`, `CompletedRepair`, `DispatchResult`
## Code Style
- Ruff with `line-length = 100` (configured in `pyproject.toml`)
- No other ruff rules explicitly configured (uses defaults)
- Ruff >= 0.4 (dev dependency)
- mypy >= 1.10 for type checking (dev dependency)
- `# type: ignore[import-untyped]` used for untyped third-party packages (aiofiles, tabulate)
## Import Organization
- Absolute imports only: `from reins.kernel.event.envelope import EventEnvelope`
- No relative imports observed
- No path aliases configured
## Type Annotations
- Use `from __future__ import annotations` for PEP 604 union syntax: `str | None`
- Dataclass fields fully typed: `active_grants: list[GrantRef] = field(default_factory=list)`
- Abstract methods use `...` as body: `async def open(self, spec: dict) -> Handle: ...`
- Generic dict payloads typed as `dict[str, Any]`
## Data Modeling
- `EventEnvelope`, `Handle`, `Observation`, `GrantRef`, `HandleRef`, `ArtifactRef`
- `PendingRepair`, `CompletedRepair`, `ContextShard`, `PolicyDecision`
- `RunState`, `StateSnapshot`, `WorkingSet`
## Error Handling
- Raise `ValueError` for invalid arguments: `raise ValueError("Graph .* not found")`
- Raise `RuntimeError` for unexpected external responses
- Return error info in result objects: `Observation(exit_code=1, stderr="path escape")`
- No custom exception hierarchy observed
## Logging
## Comments and Docstrings
## Function Design
## Module Design
- Types/models (in `types.py` files)
- Logic (in named modules like `reducer.py`, `engine.py`)
- I/O (in adapters and journal modules)
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Event-sourced state management with append-only JSONL journals
- Pure reducer functions for state transitions (no I/O in state logic)
- Capability-based policy engine with tiered risk assessment
- Handle-based execution adapters for sandboxed side effects
- Dehydration/hydration for durable, resumable runs
## Layers
- Purpose: Event sourcing primitives, state machine, routing
- Location: `src/reins/kernel/`
- Contains: EventEnvelope, EventJournal, Reducer, RunState, Router, SnapshotStore
- Depends on: Nothing (pure domain)
- Used by: All other layers
- Purpose: Evaluate capability requests against risk tiers and rules
- Location: `src/reins/policy/`
- Contains: PolicyEngine, PolicyRuleSet, ConstraintRegistry, ApprovalLedger
- Depends on: Kernel types (RiskTier, GrantRef)
- Used by: RunOrchestrator, Orchestrator
- Purpose: Dispatch trusted commands to sandboxed adapters (fs, git, shell, MCP)
- Location: `src/reins/execution/`
- Contains: Adapter ABC, ExecutionDispatcher, Handle, Observation
- Depends on: Kernel types (CommandEnvelope, HandleRef)
- Used by: RunOrchestrator
- Purpose: Assemble token-budgeted context from specs for agent sessions
- Location: `src/reins/context/`
- Contains: ContextCompilerV2, SpecProjection, TokenBudget, ContextAssemblyManifest
- Depends on: Kernel types
- Used by: RunOrchestrator (bootstrap_session, enrich_context)
- Purpose: CQRS task lifecycle (create, start, complete, archive)
- Location: `src/reins/task/`
- Contains: TaskManager (command side), TaskContextProjection (query side)
- Depends on: Kernel event journal
- Used by: RunOrchestrator, CLI
- Purpose: Multi-agent workflow coordination, pipeline execution
- Location: `src/reins/orchestration/`
- Contains: Orchestrator, Pipeline, SubagentManager, Coordinator
- Depends on: Kernel, Policy, Approval
- Used by: API server, CLI
- Purpose: Configure AI coding platforms (Claude Code, Cursor, Codex)
- Location: `src/reins/platform/`
- Contains: PlatformConfigurator, template fetcher, project detector
- Depends on: Config
- Used by: CLI init command
- Purpose: Developer workspace isolation, journal management, statistics
- Location: `src/reins/workspace/`
- Contains: WorkspaceManager, DeveloperJournal, ActivityTracker
- Depends on: Kernel event journal
- Used by: CLI workspace commands
- Purpose: Git worktree management for parallel agent execution
- Location: `src/reins/isolation/`
- Contains: WorktreeManager, AgentRegistry, WorktreeConfig
- Depends on: Kernel event journal, git subprocess
- Used by: CLI worktree commands
- Purpose: User-facing command-line interface
- Location: `src/reins/cli/`
- Contains: Typer app, subcommands for task/spec/workspace/worktree/pipeline
- Depends on: All domain layers
- Used by: End users
- Purpose: HTTP interface for programmatic run management
- Location: `src/reins/api/`
- Contains: aiohttp server, route handlers, RunRegistry
- Depends on: Kernel, Orchestration
- Used by: External agents, MCP clients
## Data Flow
- RunState is a mutable dataclass rebuilt by applying events through a pure `reduce()` function
- Events are appended to JSONL journal files (one per run_id in directory mode)
- Snapshots capture point-in-time state for fast recovery
- Dehydration serializes full run state + frozen handles into checkpoints
## Key Abstractions
- Purpose: Immutable event record with checksum, trace_id, causation chain
- Examples: `src/reins/kernel/event/envelope.py`
- Pattern: Frozen dataclass with auto-computed SHA-256 checksum
- Purpose: Stateful execution environment with open/exec/freeze/thaw lifecycle
- Examples: `src/reins/execution/adapter.py`, `src/reins/execution/adapters/`
- Pattern: Abstract base class with handle-based session management
- Purpose: Typed outcome of capability evaluation (allow/ask/deny/route_remote)
- Examples: `src/reins/policy/engine.py`
- Pattern: Frozen dataclass with risk tier, grant_id, matched rule
- Purpose: Token-budgeted context assembled from specs with audit trail
- Examples: `src/reins/context/compiler_v2.py`
- Pattern: Three-tier context (standing_law, task_contract, spec_shards)
- Purpose: Declarative multi-stage workflow with dependency DAG
- Examples: `src/reins/orchestration/pipeline.py`
- Pattern: YAML-defined stages with agent_type, prompt_template, depends_on
## Entry Points
- Location: `src/reins/cli/main.py`
- Triggers: `reins` command (via pyproject.toml `[project.scripts]`)
- Responsibilities: Parse commands, delegate to domain layers
- Location: `src/reins/api/server.py`
- Triggers: `python -m reins.api.server`
- Responsibilities: REST endpoints for run management (/runs, /runs/{id}/commands)
- Location: `src/reins/kernel/orchestrator.py`
- Triggers: API route handlers, programmatic usage
- Responsibilities: Full run lifecycle supervisor loop
## Error Handling
- `FailureClass` enum: logic_failure, context_failure, environment_failure, policy_block, etc.
- Repair loop: eval failure → classify → emit repair.required → await fix → emit repair.finished
- Policy denials return structured reasons (not exceptions)
- Validation errors return early with reason strings
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
