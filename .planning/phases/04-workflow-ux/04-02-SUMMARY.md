---
phase: "04"
plan: "02"
subsystem: "skill/brainstorm, workflow/break_loop"
tags: [brainstorm, prd, break-loop, retrospective, detection]
key-files:
  created:
    - src/reins/skill/brainstorm/__init__.py
    - src/reins/skill/brainstorm/skill.py
    - src/reins/skill/brainstorm/prd_template.py
    - src/reins/workflow/break_loop.py
    - tests/unit/test_brainstorm_skill.py
    - tests/unit/test_break_loop.py
decisions:
  - "PRDTemplate uses frozen dataclass with dict sections keyed by PRDSection enum"
  - "BreakLoopDetector checks repeated_failure before oscillation before stall"
  - "Retrospective is mutable to allow learnings to be filled post-creation"
metrics:
  tasks: 2
  tests: 24
---

# Phase 04 Plan 02: Brainstorm Skill & Break-Loop Detection Summary

Guided PRD generation skill and stuck-agent detection with structured retrospective output.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Brainstorm skill with PRD generation | de2525d | skill.py, prd_template.py |
| 2 | Break-loop detection and retrospective | f60a44b | break_loop.py |

## What Was Delivered

**Brainstorm Skill:** BrainstormSkill walks users through PRD sections via GUIDED_QUESTIONS, tracks session state through gathering/structuring/refining/complete phases, and renders structured markdown with YAML frontmatter. Required sections (overview, problem_statement, goals, requirements, acceptance_criteria) gate completion.

**Break-Loop Detector:** BreakLoopDetector monitors event streams for three pattern types — repeated_failure (same event N times), oscillation (A-B-A-B alternation), and stall (only failure events in window). When triggered, it produces a Retrospective with context, attempted actions, and failure reasons, renderable as markdown for context injection.

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- 24 tests passing (12 brainstorm + 12 break-loop)
- Both modules importable: `reins.skill.brainstorm.skill`, `reins.workflow.break_loop`
