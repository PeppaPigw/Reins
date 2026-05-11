---
phase: 05-migration-packaging
plan: 01
subsystem: packaging
tags: [uninstall, manifest, cleanup, pypi]
dependency_graph:
  requires: []
  provides: [install-manifest, cleanup-engine, uninstall-command]
  affects: [cli, pyproject]
tech_stack:
  added: []
  patterns: [frozen-dataclass-manifest, sha256-checksum-tracking]
key_files:
  created:
    - src/reins/packaging/__init__.py
    - src/reins/packaging/manifest.py
    - src/reins/packaging/cleanup.py
    - src/reins/cli/commands/uninstall.py
    - tests/unit/test_packaging_cleanup.py
    - tests/unit/test_uninstall_command.py
  modified:
    - src/reins/cli/main.py
    - src/reins/cli/commands/__init__.py
    - pyproject.toml
decisions:
  - "Manifest stored at .reins/.install-manifest.json as JSON"
  - "SHA-256 checksums detect user modifications"
  - "Directories removed deepest-first only when empty"
metrics:
  tasks_completed: 2
  tasks_total: 2
  tests_added: 19
  files_created: 6
  files_modified: 3
---

# Phase 5 Plan 1: Uninstall Command & Packaging Metadata Summary

Install manifest with SHA-256 checksum tracking, cleanup engine respecting user modifications, `reins uninstall` CLI command with --dry-run/--force/--yes flags, and complete PyPI metadata in pyproject.toml.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Install manifest tracking and cleanup logic | ab33b58 | manifest.py, cleanup.py |
| 2 | Uninstall command and packaging metadata | 48d86c4 | uninstall.py, pyproject.toml |

## Implementation Details

### Task 1: Manifest & Cleanup Engine

- `InstallManifest` tracks generated files with path, type, creator, timestamp, and SHA-256 checksum
- `CleanupEngine` plans and executes removal, skipping user-modified files unless `--force`
- Directories sorted deepest-first and removed only when empty
- 12 unit tests covering all manifest operations and cleanup scenarios

### Task 2: Uninstall Command & PyPI Metadata

- `reins uninstall` registered as top-level CLI command
- Supports `--dry-run` (show plan), `--force` (remove modified), `--yes` (skip prompt)
- Rich table output for planned removals
- pyproject.toml now includes: authors, license (MIT), readme, classifiers, urls, keywords
- `hatchling build` produces valid sdist and wheel

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- 19 tests pass (12 packaging + 7 uninstall)
- All imports resolve correctly
- `hatchling build` produces `reins-0.1.0-py3-none-any.whl`
