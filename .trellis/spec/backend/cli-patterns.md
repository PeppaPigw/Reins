# CLI Command Patterns

## Overview

Reins CLI exposes kernel functionality through a Typer-based command interface. All commands follow event-sourcing principles and integrate with existing kernel modules.

## Architecture

### Entry Point

**File:** `src/reins/cli/main.py`

```python
from reins.cli.commands import task, spec, developer, migrate, worktree, journal, status

app = typer.Typer()
app.add_typer(task.app, name="task")
app.add_typer(spec.app, name="spec")
# ... other command groups
```

**Console Entry:** `pyproject.toml`
```toml
[project.scripts]
reins = "reins.cli.main:main"
```

### Command Structure

Each command group lives in `src/reins/cli/commands/{group}.py`:

```python
import typer
from reins.cli.utils import find_repo_root, get_journal, format_table

app = typer.Typer()

@app.command()
def create(
    title: str,
    slug: str = typer.Option(None),
    priority: str = typer.Option("P1"),
) -> None:
    """Create a new task."""
    repo_root = find_repo_root()
    journal = get_journal(repo_root)
    
    # Emit event
    event = create_event_envelope(
        run_id=generate_run_id(),
        actor="cli",
        event_type="task.created",
        payload={"task_id": task_id, "title": title},
    )
    journal.append(event)
```

## Command Groups

### 1. Task Commands (`reins task`)

**File:** `src/reins/cli/commands/task.py`

```bash
reins task create "Implement feature" --type backend --priority P0
reins task list --status in_progress
reins task show task-123
reins task start task-123
reins task finish task-123
reins task archive task-123
```

**Implementation:**
- Creates task directory: `.reins/tasks/{task-id}/`
- Writes `task.json` with metadata
- Emits `task.created`, `task.started`, `task.finished`, `task.archived` events
- Updates `.reins/.current-task` pointer (format: `tasks/{task-id}`)

### 2. Task Context Commands (`reins task`)

**File:** `src/reins/cli/commands/task_context.py`

```bash
reins task init-context task-123 backend
reins task add-context task-123 implement .reins/spec/backend/error-handling.md
```

**Implementation:**
- Manages JSONL files: `implement.jsonl`, `check.jsonl`, `debug.jsonl`
- Each line is a JSON message: `{"role": "user", "content": "..."}`
- Used by hooks for context injection

### 3. Spec Commands (`reins spec`)

**File:** `src/reins/cli/commands/spec.py`

```bash
reins spec init --package cli --layers backend,frontend
reins spec list
reins spec validate .reins/spec/backend/
reins spec add-layer cli testing
```

**Implementation:**
- Creates directory structure: `.reins/spec/{package}/{layer}/`
- Generates `index.md` with Pre-Development Checklist template
- Validates YAML manifests

### 4. Developer Commands (`reins developer`)

**File:** `src/reins/cli/commands/developer.py`

```bash
reins developer init "Alice"
reins developer show
reins developer workspace-info
```

**Implementation:**
- Creates `.reins/.developer` file
- Creates workspace: `.reins/workspace/{name}/`
- Initializes journal: `.reins/workspace/{name}/journal-1.md`

### 5. Migration Commands (`reins migrate`)

**File:** `src/reins/cli/commands/migrate.py`

```bash
reins migrate run --from 0.0.0 --to 0.1.0 --dry-run
reins migrate list
reins migrate validate migrations/manifests/0.1.0.json
```

**Implementation:**
- Uses `MigrationEngine` from Phase 3
- Supports dry-run mode
- Validates against JSON schema

### 6. Worktree Commands (`reins worktree`)

**File:** `src/reins/cli/commands/worktree.py`

```bash
reins worktree create agent-1 task-123 --branch feat/task-123
reins worktree list --active-only
reins worktree verify wt-123
reins worktree cleanup wt-123 --force
reins worktree cleanup-orphans
```

**Implementation:**
- Uses `WorktreeManager` from Phase 3
- Loads config from `.reins/worktree.yaml`
- Registers agents in `AgentRegistry`

### 7. Journal Commands (`reins journal`)

**File:** `src/reins/cli/commands/journal.py`

```bash
reins journal show --limit 10 --type task.*
reins journal replay --from 2026-04-18T10:00:00Z
reins journal export output.json --format json
reins journal stats
```

**Implementation:**
- Reads from `EventJournal`
- Supports filtering by type, timestamp, actor
- Implements replay for state reconstruction

### 8. Status Command (`reins status`)

**File:** `src/reins/cli/commands/status.py`

```bash
reins status
reins status --verbose
```

**Implementation:**
- Shows current task from `.reins/.current-task`
- Shows active agents from `AgentRegistry`
- Shows git status
- Shows recent journal events

## Shared Utilities

**File:** `src/reins/cli/utils.py`

### Repo Discovery

```python
def find_repo_root() -> Path:
    """Walk up from cwd to find .reins directory."""
    current = Path.cwd()
    while current != current.parent:
        if (current / ".reins").exists():
            return current
        current = current.parent
    raise ValueError("Not in a Reins repository")
```

### Journal Access

```python
def get_journal(repo_root: Path) -> EventJournal:
    """Load EventJournal from repo."""
    return EventJournal(repo_root / ".reins" / "journal.jsonl")
```

### Formatting

```python
def format_timestamp(dt: datetime) -> str:
    """Human-readable timestamp: '2026-04-18 10:30:22'"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def format_table(data: list[dict], headers: list[str]) -> str:
    """Format data as table using tabulate."""
    return tabulate(data, headers=headers, tablefmt="simple")
```

### Run ID Generation

```python
def generate_run_id() -> str:
    """Generate unique run ID: 'cli-20260418-103022-abc123'"""
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    random_suffix = secrets.token_hex(3)
    return f"cli-{timestamp}-{random_suffix}"
```

## Event Sourcing Pattern

Every state-changing command follows this pattern:

```python
@app.command()
def mutating_command(arg: str) -> None:
    # 1. Find repo and load journal
    repo_root = find_repo_root()
    journal = get_journal(repo_root)
    
    # 2. Perform operation
    result = perform_operation(arg)
    
    # 3. Emit event
    event = create_event_envelope(
        run_id=generate_run_id(),
        actor="cli",
        event_type="operation.completed",
        payload={"arg": arg, "result": result},
    )
    journal.append(event)
    
    # 4. Update filesystem artifacts
    write_artifact(repo_root, result)
    
    # 5. Display result
    console.print(f"[green]✓[/green] Operation completed")
```

## Error Handling

```python
@app.command()
def command_with_errors() -> None:
    try:
        repo_root = find_repo_root()
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    
    try:
        perform_operation()
    except Exception as e:
        # Emit error event
        journal.append(create_event_envelope(
            run_id=generate_run_id(),
            actor="cli",
            event_type="cli.error",
            payload={"error": str(e)},
        ))
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
```

## Testing Pattern

**File:** `tests/unit/test_cli_task.py`

```python
from typer.testing import CliRunner
from reins.cli.main import app

runner = CliRunner()

def test_task_create(tmp_path):
    # Setup
    (tmp_path / ".reins").mkdir()
    (tmp_path / ".reins" / "tasks").mkdir()
    
    # Execute
    result = runner.invoke(app, [
        "task", "create", "Test task",
        "--type", "backend",
        "--priority", "P0",
    ], cwd=tmp_path)
    
    # Assert
    assert result.exit_code == 0
    assert "Task created" in result.stdout
    
    # Verify filesystem
    task_dirs = list((tmp_path / ".reins" / "tasks").iterdir())
    assert len(task_dirs) == 1
    
    # Verify event
    journal = EventJournal(tmp_path / ".reins" / "journal.jsonl")
    events = list(journal.read_all())
    assert any(e.event_type == "task.created" for e in events)
```

## Current Task Pointer Format

**File:** `.reins/.current-task`

**Format:** `tasks/{task-id}` (relative to `.reins/`)

**Example:**
```
tasks/04-18-implement-auth
```

**Normalization (Phase 4):**
- CLI commands write `tasks/{task-id}`
- Hooks read `tasks/{task-id}`
- Worktree manager writes `tasks/{task-id}` in worktrees
- Tests expect `tasks/{task-id}`

**Previous format:** Mixed `.reins/tasks/{task-id}` and `tasks/{task-id}`

## Dependencies

**Added in Phase 4:**
```toml
[project.dependencies]
typer = "^0.9.0"
rich = "^13.7.0"
tabulate = "^0.9.0"
```

## Best Practices

### 1. Always Emit Events

```python
# GOOD: Emit event for state change
journal.append(create_event_envelope(...))

# BAD: Mutate state without event
write_file(path, content)  # No event!
```

### 2. Use Existing Kernel Modules

```python
# GOOD: Use WorktreeManager
manager = WorktreeManager(journal, run_id, repo_root)
await manager.create_worktree_for_agent(...)

# BAD: Call git directly
subprocess.run(["git", "worktree", "add", ...])
```

### 3. Validate Input Early

```python
# GOOD: Validate before mutation
if not task_id.match(r"^\d{2}-\d{2}-[a-z0-9-]+$"):
    raise ValueError("Invalid task ID format")

# BAD: Validate after mutation
write_file(...)
if not valid:  # Too late!
    raise ValueError(...)
```

### 4. Use Rich for Output

```python
# GOOD: Rich formatting
console.print("[green]✓[/green] Task created")
console.print(Panel(content, title="Task Details"))

# BAD: Plain print
print("Task created")
```

## Anti-Patterns

### ❌ Don't Skip Event Emission

```python
# BAD: Direct filesystem mutation
def create_task(title: str):
    task_dir.mkdir()
    write_json(task_dir / "task.json", data)
    # No event emitted!
```

### ❌ Don't Duplicate Kernel Logic

```python
# BAD: Reimplementing worktree logic
def create_worktree(path: str):
    subprocess.run(["git", "worktree", "add", path])
    copy_files(...)
    # Duplicates WorktreeManager!

# GOOD: Use kernel module
manager.create_worktree_for_agent(...)
```

### ❌ Don't Ignore Errors

```python
# BAD: Silent failure
try:
    perform_operation()
except Exception:
    pass  # User doesn't know it failed!

# GOOD: Report and exit
except Exception as e:
    console.print(f"[red]Error:[/red] {e}")
    raise typer.Exit(1)
```

## References

- [Phase 4 Design](../../docs/plans/2026-04-18-cli-commands-design.md)
- [Phase 4 Implementation](../../docs/plans/2026-04-18-cli-commands-implementation.md)
- [Typer Documentation](https://typer.tiangolo.com/)
- [Rich Documentation](https://rich.readthedocs.io/)
