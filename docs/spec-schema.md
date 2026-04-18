# Spec Manifest Schema

Specs are stored as YAML files with metadata and content. This document describes the schema.

## File Format

```yaml
spec_type: standing_law | task_contract | spec_shard
scope: workspace | task:{task_id}
precedence: 100
visibility_tier: 0-3
required_capabilities:
  - capability1
  - capability2
applicability:
  task_type: backend | frontend | fullstack | null
  run_phase: implement | check | debug | null
  actor_type: implement-agent | check-agent | null
  path_pattern: "*.py" | null
content: |
  # Spec Content (Markdown)

  Your spec content goes here...
```

## Fields

### Required Fields

#### `content` (string)
The actual spec content in Markdown format. This is what gets injected into agent context.

### Optional Fields (with defaults)

#### `spec_type` (string, default: `standing_law`)
Type of spec determines when it's included:
- `standing_law`: Always included in seed context (project conventions, coding standards)
- `task_contract`: Included when a task is active (task requirements, acceptance criteria)
- `spec_shard`: Included on-demand based on applicability (phase-specific guidance)

#### `scope` (string, default: `workspace`)
Scope determines visibility:
- `workspace`: Available to all runs in this workspace
- `task:{task_id}`: Only available when working on specific task

#### `precedence` (integer, default: `100`)
Priority for conflict resolution. Higher values win.
- `200`: High priority (overrides other specs)
- `100`: Standard priority
- `50`: Low priority (fallback guidance)

#### `visibility_tier` (integer, default: `1`)
Controls who sees this spec:
- `0`: Always visible (core conventions)
- `1`: Standard (shown by default)
- `2`: Advanced (opt-in for experienced users)
- `3`: Expert (opt-in for specific scenarios)

#### `required_capabilities` (list, default: `[]`)
Capabilities required to see this spec. Used for visibility filtering.

Examples:
- `["fs:write"]`: Only show to agents that can write files
- `["git:commit"]`: Only show to agents that can commit
- `[]`: Show to everyone

#### `applicability` (dict, default: `{}`)
Criteria for when this spec applies. All fields are optional.

Fields:
- `task_type`: Apply to specific task types (`backend`, `frontend`, `fullstack`)
- `run_phase`: Apply to specific phases (`implement`, `check`, `debug`)
- `actor_type`: Apply to specific actors (`implement-agent`, `check-agent`)
- `path_pattern`: Apply when working on files matching pattern (`*.py`, `src/**/*.ts`)

## Examples

### Standing Law: Always-On Convention

```yaml
spec_type: standing_law
scope: workspace
precedence: 100
visibility_tier: 0
required_capabilities:
  - fs:write
applicability:
  task_type: backend
  run_phase: null
  actor_type: null
  path_pattern: null
content: |
  # Error Handling

  Always use structured error types...
```

### Task Contract: Task-Specific Requirements

```yaml
spec_type: task_contract
scope: task:04-17-implement-auth
precedence: 200
visibility_tier: 0
required_capabilities: []
applicability:
  task_type: null
  run_phase: null
  actor_type: null
  path_pattern: null
content: |
  # Task: Implement JWT Authentication

  ## Requirements
  - Use RS256 algorithm
  - Store tokens in Redis
  - 15-minute expiry
```

### Spec Shard: Phase-Specific Guidance

```yaml
spec_type: spec_shard
scope: workspace
precedence: 100
visibility_tier: 1
required_capabilities:
  - fs:read
applicability:
  task_type: null
  run_phase: check
  actor_type: check-agent
  path_pattern: null
content: |
  # Code Review Checklist

  When reviewing code, check for...
```

## Validation Rules

1. `content` field is required and must be a string
2. `spec_type` must be one of: `standing_law`, `task_contract`, `spec_shard`
3. `visibility_tier` must be an integer between 0 and 3
4. `precedence` must be an integer
5. `required_capabilities` must be a list of strings
6. `applicability` must be a dict

## File Naming

Spec files should be named descriptively and organized by category:

```
.reins/spec/
├── backend/
│   ├── error-handling.yaml
│   ├── logging.yaml
│   └── testing.yaml
├── frontend/
│   ├── component-structure.yaml
│   └── state-management.yaml
└── guides/
    ├── code-review.yaml
    └── debugging.yaml
```

The spec_id is generated from the file path:
- `backend/error-handling.yaml` → `backend.error-handling`
- `frontend/component-structure.yaml` → `frontend.component-structure`
