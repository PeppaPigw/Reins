---
phase: 09-testing-ci
plan: 01
status: complete
completed_at: "2026-05-11"
---

## Summary

Configured per-module coverage measurement and added a coverage gate to CI.

## Artifacts Created

- `src/reins/testing/__init__.py` — Testing utilities package init
- `src/reins/testing/coverage_config.py` (172 lines) — Coverage targets, report parsing, gate checking, table formatting
- `.github/workflows/ci.yml` (62 lines) — Updated CI with `--cov` flags and coverage gate step
- `tests/unit/test_coverage_config.py` (166 lines) — 10 tests covering all coverage config functionality

## Changes to Existing Files

- `pyproject.toml` — Added `pytest-cov>=5.0` to dev deps; added `[tool.coverage.run]`, `[tool.coverage.report]`, and `[tool.coverage.json]` sections

## Coverage Targets Defined

| Module | Target |
|--------|--------|
| reins.kernel | 90% |
| reins.policy | 90% |
| reins.execution | 85% |
| reins.context | 85% |
| reins.workflow | 85% |
| reins.packaging | 80% |
| reins.integrations | 75% |

## Verification

- All 10 unit tests pass
- Module imports successfully
- CI YAML validates
- pyproject.toml parses correctly
