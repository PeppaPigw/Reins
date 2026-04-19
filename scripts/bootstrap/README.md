# Bootstrap Scripts

These helpers create native `.reins/tasks/<task-id>/` task directories and seed them with workflow-specific templates.

## Feature bootstrap

```bash
python3 scripts/bootstrap/feature.py "Add user authentication"
```

Creates a task, writes a feature PRD template, and runs the selected pipeline into `pipeline-output/`.

## Bug-fix bootstrap

```bash
python3 scripts/bootstrap/bugfix.py "Fix login timeout" --file src/auth/login.py
```

Creates a task, writes `bug-report.md`, and runs the debug pipeline into `debug-output/`.

## TDD bootstrap

```bash
python3 scripts/bootstrap/tdd.py "Add user validation" --module validate_user
```

Creates a task plus starter test and implementation templates. Use `--pipeline` when you also want to run a pipeline after scaffolding.
