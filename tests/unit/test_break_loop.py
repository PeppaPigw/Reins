"""Tests for break-loop detection and retrospective trigger."""

from __future__ import annotations

from reins.workflow.break_loop import BreakLoopDetector, LoopPattern, Retrospective


class TestBreakLoopDetector:
    def setup_method(self) -> None:
        self.detector = BreakLoopDetector(threshold=3, window_seconds=60.0)

    def test_no_detection_below_threshold(self) -> None:
        result = self.detector.record_event("command.failed", timestamp=1.0)
        assert result is None
        result = self.detector.record_event("command.failed", timestamp=2.0)
        assert result is None

    def test_repeated_failure_detected_at_threshold(self) -> None:
        self.detector.record_event("command.failed", timestamp=1.0)
        self.detector.record_event("command.failed", timestamp=2.0)
        result = self.detector.record_event("command.failed", timestamp=3.0)
        assert result is not None
        assert result.pattern_type == "repeated_failure"
        assert result.count >= 3
        assert "command.failed" in result.event_types

    def test_repeated_failure_not_detected_outside_window(self) -> None:
        # Events spread beyond the 60s window
        self.detector.record_event("command.failed", timestamp=1.0)
        self.detector.record_event("command.failed", timestamp=2.0)
        # This event is 100s later, first event should be pruned
        result = self.detector.record_event("command.failed", timestamp=100.0)
        assert result is None

    def test_oscillation_detected(self) -> None:
        # Use patterns that won't trigger repeated_failure detection
        detector = BreakLoopDetector(
            threshold=3, window_seconds=60.0, patterns=["unrelated.error"]
        )
        base = 1.0
        # A->B->A->B->A->B pattern (3 oscillations)
        detector.record_event("fix.applied", timestamp=base)
        detector.record_event("test.failed", timestamp=base + 1)
        detector.record_event("fix.applied", timestamp=base + 2)
        detector.record_event("test.failed", timestamp=base + 3)
        detector.record_event("fix.applied", timestamp=base + 4)
        result = detector.record_event("test.failed", timestamp=base + 5)
        assert result is not None
        assert result.pattern_type == "oscillation"
        assert "fix.applied" in result.event_types
        assert "test.failed" in result.event_types

    def test_stall_detected_no_progress(self) -> None:
        # All events are failure patterns — stall
        base = 1.0
        self.detector.record_event("command.failed", timestamp=base)
        self.detector.record_event("eval.failed", timestamp=base + 1)
        result = self.detector.record_event("repair.required", timestamp=base + 2)
        assert result is not None
        assert result.pattern_type == "stall"

    def test_record_event_returns_pattern_on_detection(self) -> None:
        result = None
        for i in range(5):
            result = self.detector.record_event(
                "command.failed", timestamp=float(i)
            )
        assert result is not None
        assert isinstance(result, LoopPattern)

    def test_record_event_returns_none_when_no_pattern(self) -> None:
        result = self.detector.record_event("task.completed", timestamp=1.0)
        assert result is None

    def test_trigger_retrospective_creates_structured_output(self) -> None:
        pattern = LoopPattern(
            pattern_type="repeated_failure",
            event_types=("command.failed",),
            count=3,
            window_seconds=60.0,
        )
        retro = self.detector.trigger_retrospective(
            pattern, task_id="task-123", context="Building auth module"
        )
        assert isinstance(retro, Retrospective)
        assert retro.task_id == "task-123"
        assert retro.trigger == pattern
        assert retro.context_summary == "Building auth module"
        assert len(retro.failure_reasons) > 0

    def test_format_retrospective_produces_markdown(self) -> None:
        pattern = LoopPattern(
            pattern_type="oscillation",
            event_types=("fix.applied", "eval.failed"),
            count=4,
            window_seconds=30.0,
        )
        retro = Retrospective(
            task_id="task-456",
            trigger=pattern,
            timestamp="2025-01-01T00:00:00+00:00",
            context_summary="Agent stuck fixing auth",
            attempted_actions=["fix.applied", "eval.failed"],
            failure_reasons=["oscillation: fix.applied, eval.failed repeated 4 times"],
            learnings=["Need different approach"],
            suggested_next="Try alternative auth strategy",
        )
        md = self.detector.format_retrospective(retro)
        assert "## Retrospective" in md
        assert "oscillation" in md
        assert "task-456" in md
        assert "Agent stuck fixing auth" in md
        assert "fix.applied" in md
        assert "Need different approach" in md
        assert "Try alternative auth strategy" in md

    def test_reset_clears_buffer(self) -> None:
        self.detector.record_event("command.failed", timestamp=1.0)
        self.detector.record_event("command.failed", timestamp=2.0)
        self.detector.reset()
        # After reset, threshold not met
        result = self.detector.record_event("command.failed", timestamp=3.0)
        assert result is None

    def test_custom_patterns_configuration(self) -> None:
        detector = BreakLoopDetector(
            threshold=2,
            window_seconds=30.0,
            patterns=["custom.error"],
        )
        detector.record_event("custom.error", timestamp=1.0)
        result = detector.record_event("custom.error", timestamp=2.0)
        assert result is not None
        assert result.pattern_type == "repeated_failure"
        assert "custom.error" in result.event_types

    def test_multiple_pattern_types_independent(self) -> None:
        # One failure type below threshold shouldn't trigger
        self.detector.record_event("command.failed", timestamp=1.0)
        self.detector.record_event("eval.failed", timestamp=2.0)
        result = self.detector.record_event("repair.required", timestamp=3.0)
        # This triggers stall (all are failure patterns)
        assert result is not None
        assert result.pattern_type == "stall"
