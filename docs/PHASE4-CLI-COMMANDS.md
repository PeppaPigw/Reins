# Phase 4: CLI Commands for Task and Spec Management

## Overview

Implement CLI commands that expose Reins kernel functionality. Commands bridge Python kernel with user workflows.

## Task Breakdown

### 1. Task Lifecycle Commands

**Files to create:**
- `src/reins/cli/commands/task.py` - Task CRUD operations
- `src/reins/cli/commands/task_context.py` - Context management

**Commands:**
```bash
reins task create <title> [--slug NAME] [--package PKG] [--priority P0-P3]
reins task list [--status STATUS] [--assignee NAME]
reins task show <task-id>
reins task start <task-id>
reins task finish <task-id>
reins task archive <task-id>
reins task add-context <task-id> <agent> <file-path> [--reason TEXT]
reins task init-context <task-id> <type>  # type: backend|frontend|fullstack
```

**Implementation requirements:**
- Use `EventJournal` for all state changes
- Emit events: `task.created`, `task.started`, `task.finished`, `task.archived`
- Update `.reins/.current-task` pointer
- Validate task directory structure
- Handle JSONL context files (implement.jsonl, check.jsonl, debug.jsonl)

### 2. Spec Management Commands

**Files to create:**
- `src/reins/cli/commands/spec.py` - Spec operations

**Commands:**
```bash
reins spec init [--package PKG] [--layers LAYERS]
reins spec list [--package PKG]
reins spec validate <spec-dir>
reins spec add-layer <package> <layer-name>
```

**Implementation requirements:**
- Create spec directory structure: `.reins/spec/{package}/{layer}/`
- Generate index.md with Pre-Development Checklist template
- Validate spec files against schema
- Support custom layer names

### 3. Developer Identity Commands

**Files to create:**
- `src/reins/cli/commands/developer.py` - Developer management

**Commands:**
```bash
reins developer init <name>
reins developer show
reins developer workspace-info
```

**Implementation requirements:**
- Create `.reins/.developer` file
- Create workspace directory: `.reins/workspace/{name}/`
- Initialize journal: `.reins/workspace/{name}/journal-1.md`
- Track session count and line limits

### 4. Migration Commands

**Files to create:**
- `src/reins/cli/commands/migrate.py` - Migration operations

**Commands:**
```bash
reins migrate run --from VERSION --to VERSION [--dry-run]
reins migrate list
reins migrate validate <manifest-file>
reins migrate create <version>
```

**Implementation requirements:**
- Use `MigrationEngine` from Phase 3
- Support dry-run mode
- Show migration preview before applying
- Validate manifests against schema

### 5. Worktree Commands

**Files to create:**
- `src/reins/cli/commands/worktree.py` - Worktree operations

**Commands:**
```bash
reins worktree create <agent-id> <task-id> --branch NAME [--base BRANCH]
reins worktree list [--active-only]
reins worktree verify <worktree-id>
reins worktree cleanup <worktree-id> [--force]
reins worktree cleanup-orphans [--force]
```

**Implementation requirements:**
- Use `WorktreeManager` from Phase 3
- Load config from `.reins/worktree.yaml`
- Register agents in `AgentRegistry`
- Handle verification hooks

### 6. Journal Commands

**Files to create:**
- `src/reins/cli/commands/journal.py` - Journal operations

**Commands:**
```bash
reins journal show [--limit N] [--type EVENT_TYPE]
reins journal replay --from TIMESTAMP [--to TIMESTAMP]
reins journal export <output-file> [--format json|jsonl]
reins journal stats
```

**Implementation requirements:**
- Read from `EventJournal`
- Support filtering by event type, timestamp, actor
- Implement replay for state reconstruction
- Show statistics: event counts, types, actors

### 7. Status Commands

**Files to create:**
- `src/reins/cli/commands/status.py` - Status display

**Commands:**
```bash
reins status
reins status --verbose
```

**Implementation requirements:**
- Show current task
- Show active agents (from registry)
- Show git status
- Show recent journal events
- Show workspace info

## CLI Framework

**Files to create:**
- `src/reins/cli/__init__.py` - CLI entry point
- `src/reins/cli/main.py` - Command dispatcher
- `src/reins/cli/utils.py` - Shared utilities

**Framework choice:** Click or Typer
- Typer recommended (type hints, async support)
- Rich for colored output
- Tabulate for tables

**Common utilities:**
- `find_repo_root()` - Locate .reins directory
- `load_config()` - Load .reins/config.yaml
- `format_timestamp()` - Human-readable timestamps
- `format_table()` - Consistent table formatting

## Testing Strategy

**Test files to create:**
- `tests/unit/test_cli_task.py`
- `tests/unit/test_cli_spec.py`
- `tests/unit/test_cli_developer.py`
- `tests/unit/test_cli_migrate.py`
- `tests/unit/test_cli_worktree.py`
- `tests/unit/test_cli_journal.py`
- `tests/integration/test_cli_workflows.py`

**Test coverage:**
- Command parsing and validation
- Error handling (missing files, invalid input)
- Event emission verification
- File system operations
- Integration with kernel modules

## Dependencies

**New dependencies to add:**
- `typer` - CLI framework
- `rich` - Terminal formatting
- `tabulate` - Table formatting
- `pyyaml` - YAML config parsing (already have)

## Success Criteria

- [ ] All 7 command groups implemented
- [ ] Commands emit events to journal
- [ ] Commands integrate with existing kernel modules
- [ ] Help text and examples for all commands
- [ ] Error messages are clear and actionable
- [ ] Unit tests for all commands
- [ ] Integration test for complete workflow
- [ ] Documentation in `.reins/spec/cli/`
