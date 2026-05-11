# Quick Start Guide

Get from install to your first completed task in under 5 minutes.

## Prerequisites

- Python 3.11 or later
- Git (any recent version)
- A project repository you want to manage with Reins

## Installation

Install Reins from PyPI:

```bash
pip install reins
```

Verify the installation:

```bash
reins --version
```

## Initialize Your Project (1 minute)

Navigate to your project root and run:

```bash
cd your-project
reins init --platform claude
```

This creates the `.reins/` directory structure:

```
.reins/
  config.yaml          # Project configuration
  journal.jsonl        # Event journal (append-only audit log)
  tasks/               # Task metadata and context
  workspace/           # Developer workspace state
  spec/                # Specification files
```

Reins auto-detects your project type (backend, frontend, fullstack) and
configures platform-specific templates for your AI coding assistant.

### Available Platforms

| Platform | Flag |
|----------|------|
| Claude Code | `--platform claude` |
| Cursor | `--platform cursor` |
| Codex | `--platform codex` |

You can also let Reins auto-detect the platform:

```bash
reins init
```

## Create Your First Task (1 minute)

Create a task to track your work:

```bash
reins task create "Implement user authentication" --type backend --priority P1
```

Expected output:

```
Created task: 05-11-implement-user-authentication
  Type: backend
  Priority: P1
  Status: planning
```

Tasks follow a lifecycle: `planning` -> `in_progress` -> `checking` -> `done`.

Check your task:

```bash
reins task list
```

## Start Working (2 minutes)

Start the task to transition it to `in_progress`:

```bash
reins task start 05-11-implement-user-authentication
```

When you start a task, Reins:

1. Injects relevant context into your AI assistant's session
2. Sets up spec-driven guardrails for the work
3. Begins recording events to the audit journal

Your AI coding assistant now has structured context about what to build,
including relevant specs, constraints, and acceptance criteria.

## Check Status

View overall project status:

```bash
reins status
```

List all tasks with their current state:

```bash
reins task list
```

View the event journal for a specific run:

```bash
reins replay events <run-id>
```

## Complete the Task

When work is done, mark the task as complete:

```bash
reins task complete 05-11-implement-user-authentication
```

This records a completion event in the journal, providing a full audit
trail of what was done and when.

## Next Steps

Once you are comfortable with the basics, explore these features:

- **Add more platforms:** `reins init --platform cursor`
- **Run diagnostics:** `reins doctor` (coming soon)
- **Update configurations:** `reins update`
- **Manage specs:** `reins spec init --package cli`
- **Parallel execution:** `reins worktree create feature-lane --task <id>`
- **Pipeline orchestration:** `reins pipeline run <pipeline.yaml>`
- **Journal statistics:** `reins journal stats`

## Common Issues

### "No .reins directory found"

Run `reins init` in your project root first.

### "Unknown platform"

Check available platforms with `reins init --help`. Use the exact flag
value from the table above.

### "Task not found"

List tasks with `reins task list` to see available task IDs. Task IDs
are generated from the creation date and title.

### Need more help?

- Run `reins --help` for all available commands
- Run `reins <command> --help` for command-specific options
- Check the event journal: `reins journal stats`
