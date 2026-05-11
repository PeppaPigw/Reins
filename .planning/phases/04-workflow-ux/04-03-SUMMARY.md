---
phase: 04-workflow-ux
plan: 03
subsystem: workflow/learning
tags: [retrospective, learning, knowledge-base, spec-update, context-injection]
dependency_graph:
  requires: [04-01, 04-02]
  provides: [RetrospectiveStore, LearningExtractor, LearningFlow, LearningInjector]
  affects: [context compilation, spec system]
tech_stack:
  added: []
  patterns: [JSONL persistence, frozen dataclasses, confidence scoring, XML injection]
key_files:
  created:
    - src/reins/workflow/retrospective.py
    - src/reins/workflow/learning.py
    - src/reins/context/learning_injection.py
    - tests/unit/test_retrospective_capture.py
    - tests/unit/test_learning_flow.py
decisions:
  - JSONL file-per-concern (retrospectives.jsonl, learnings.jsonl) for simple append-only storage
  - Confidence scoring based on trigger pattern repetition count (5+ -> 0.9, 3+ -> 0.7, else 0.5)
  - Category heuristics use keyword matching on learning text
metrics:
  duration: 3m
  completed: 2026-05-11
  tasks: 2/2
  tests: 22
---

# Phase 4 Plan 3: Retrospective Persistence & Learning Flow Summary

Event-sourced learning pipeline: retrospectives persist to JSONL knowledge base, learnings are extracted with confidence scoring and category heuristics, high-confidence learnings produce spec-update proposals, and past learnings inject into future agent context via XML tags.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | ce9674a | Retrospective persistence and knowledge base |
| 2 | a9f9a92 | Learning extraction and spec-update flow |

## Key Deliverables

- **RetrospectiveStore**: JSONL-backed persistence for retrospectives and learnings with query/filter by task_type and file_pattern
- **Learning**: Frozen dataclass with confidence validation (0.0-1.0)
- **LearningExtractor**: Derives structured learnings from retrospectives, assigns categories via keyword heuristics, scores confidence from pattern repetition
- **LearningFlow**: Full pipeline orchestrating save -> extract -> propose
- **SpecUpdateProposal**: Maps anti_pattern learnings to constraint specs, patterns to guidance specs
- **LearningInjector**: Queries relevant learnings and formats as plain text or XML for context injection

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED
