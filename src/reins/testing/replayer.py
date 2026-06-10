from __future__ import annotations

import time
from typing import Any

from reins.testing.replay_types import (
    AssertionKind,
    GoldenSnapshot,
    Mutation,
    MutationKind,
    RecordedEvent,
    RecordedToolCall,
    ReplayAssertion,
    ReplayConfig,
    ReplayMode,
    ReplayResult,
    SessionRecording,
)


class AssertionFailure(Exception):
    def __init__(self, assertion: ReplayAssertion, actual: Any, message: str = ""):
        self.assertion = assertion
        self.actual = actual
        self.message = message
        super().__init__(message or f"Assertion {assertion.kind.value} failed")


class SessionReplayer:
    """Replays recorded sessions with assertions and fault injection.

    Supports three replay modes:
    - STRICT: exact match against recording (deterministic regression)
    - RELAXED: structural match with tolerance for timing/ordering
    - MUTATION: inject faults to test resilience
    """

    def __init__(self, recording: SessionRecording, config: ReplayConfig | None = None) -> None:
        self._recording = recording
        self._config = config or ReplayConfig()
        self._mutations_by_seq: dict[int, Mutation] = {}
        self._mutations_by_tool: dict[str, Mutation] = {}

        for m in self._config.mutations:
            if m.target_sequence is not None:
                self._mutations_by_seq[m.target_sequence] = m
            if m.target_tool is not None:
                self._mutations_by_tool[m.target_tool] = m

    @property
    def recording(self) -> SessionRecording:
        return self._recording

    @property
    def config(self) -> ReplayConfig:
        return self._config

    async def replay(self) -> ReplayResult:
        start = time.perf_counter()
        failures: list[str] = []
        diffs: list[dict[str, Any]] = []
        passed_count = 0

        replayed_events = self._apply_mutations_to_events(list(self._recording.events))
        replayed_tools = self._apply_mutations_to_tools(list(self._recording.tool_calls))

        for assertion in self._config.assertions:
            try:
                self._check_assertion(assertion, replayed_events, replayed_tools)
                passed_count += 1
            except AssertionFailure as e:
                failures.append(f"{e.assertion.kind.value}: {e.message}")
                if self._config.capture_diffs:
                    diffs.append({
                        "assertion": e.assertion.kind.value,
                        "expected": e.assertion.expected,
                        "actual": e.actual,
                        "description": e.assertion.description,
                    })
                if self._config.stop_on_first_failure:
                    break

        elapsed = (time.perf_counter() - start) * 1000

        return ReplayResult(
            recording_id=self._recording.recording_id,
            passed=len(failures) == 0,
            total_assertions=len(self._config.assertions),
            passed_assertions=passed_count,
            failed_assertions=tuple(failures),
            diffs=tuple(diffs),
            duration_ms=elapsed,
        )

    def _apply_mutations_to_events(self, events: list[RecordedEvent]) -> list[RecordedEvent]:
        result = []
        for event in events:
            mutation = self._mutations_by_seq.get(event.sequence)
            if mutation:
                if mutation.kind == MutationKind.DROP_EVENT:
                    continue
                if mutation.kind == MutationKind.INJECT_FAILURE:
                    result.append(RecordedEvent(
                        sequence=event.sequence,
                        event_type="error.injected",
                        payload={"original_type": event.event_type, **mutation.parameters},
                    ))
                    continue
            result.append(event)

        reorder_mutations = [m for m in self._config.mutations if m.kind == MutationKind.REORDER_EVENTS]
        if reorder_mutations:
            result.reverse()

        return result

    def _apply_mutations_to_tools(self, tools: list[RecordedToolCall]) -> list[RecordedToolCall]:
        result = []
        for call in tools:
            mutation = self._mutations_by_seq.get(call.sequence) or self._mutations_by_tool.get(call.tool_name)
            if mutation:
                if mutation.kind == MutationKind.INJECT_FAILURE:
                    result.append(RecordedToolCall(
                        sequence=call.sequence,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        result=None,
                        error=mutation.parameters.get("error", "injected failure"),
                        duration_ms=call.duration_ms,
                    ))
                    continue
                if mutation.kind == MutationKind.TIMEOUT:
                    result.append(RecordedToolCall(
                        sequence=call.sequence,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        result=None,
                        error="timeout",
                        duration_ms=mutation.parameters.get("timeout_ms", 30000),
                    ))
                    continue
                if mutation.kind == MutationKind.CORRUPT_OUTPUT:
                    result.append(RecordedToolCall(
                        sequence=call.sequence,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                        result="CORRUPTED",
                        error=None,
                        duration_ms=call.duration_ms,
                    ))
                    continue
            result.append(call)
        return result

    def _check_assertion(
        self,
        assertion: ReplayAssertion,
        events: list[RecordedEvent],
        tools: list[RecordedToolCall],
    ) -> None:
        if assertion.kind == AssertionKind.EVENT_SEQUENCE:
            self._assert_event_sequence(assertion, events)
        elif assertion.kind == AssertionKind.TOOL_CALL_MATCH:
            self._assert_tool_call_match(assertion, tools)
        elif assertion.kind == AssertionKind.OUTPUT_EXACT:
            self._assert_output_exact(assertion, tools)
        elif assertion.kind == AssertionKind.OUTPUT_CONTAINS:
            self._assert_output_contains(assertion, tools)
        elif assertion.kind == AssertionKind.TIMING_BOUND:
            self._assert_timing_bound(assertion, events, tools)
        elif assertion.kind == AssertionKind.NO_REGRESSION:
            self._assert_no_regression(assertion, events, tools)
        elif assertion.kind == AssertionKind.STATE_SNAPSHOT:
            self._assert_state_snapshot(assertion, events)

    def _assert_event_sequence(self, assertion: ReplayAssertion, events: list[RecordedEvent]) -> None:
        expected_types = assertion.expected
        if not isinstance(expected_types, list):
            raise AssertionFailure(assertion, None, "expected must be a list of event types")

        actual_types = [e.event_type for e in events]

        if self._config.mode == ReplayMode.STRICT:
            if actual_types != expected_types:
                raise AssertionFailure(assertion, actual_types, f"Event sequence mismatch: expected {expected_types}, got {actual_types}")
        else:
            for expected_type in expected_types:
                if expected_type not in actual_types:
                    raise AssertionFailure(assertion, actual_types, f"Missing event type: {expected_type}")

    def _assert_tool_call_match(self, assertion: ReplayAssertion, tools: list[RecordedToolCall]) -> None:
        target = assertion.target
        matching = [t for t in tools if t.tool_name == target]
        if not matching:
            raise AssertionFailure(assertion, [], f"No tool calls found for '{target}'")

        if assertion.expected is not None:
            expected_count = assertion.expected
            if isinstance(expected_count, int) and len(matching) != expected_count:
                raise AssertionFailure(assertion, len(matching), f"Expected {expected_count} calls to '{target}', got {len(matching)}")

    def _assert_output_exact(self, assertion: ReplayAssertion, tools: list[RecordedToolCall]) -> None:
        target = assertion.target
        matching = [t for t in tools if t.tool_name == target]
        if not matching:
            raise AssertionFailure(assertion, None, f"No tool calls for '{target}'")

        last_result = matching[-1].result
        if last_result != assertion.expected:
            raise AssertionFailure(assertion, last_result, f"Output mismatch for '{target}'")

    def _assert_output_contains(self, assertion: ReplayAssertion, tools: list[RecordedToolCall]) -> None:
        target = assertion.target
        matching = [t for t in tools if t.tool_name == target]
        if not matching:
            raise AssertionFailure(assertion, None, f"No tool calls for '{target}'")

        last_result = str(matching[-1].result or "")
        expected_substr = str(assertion.expected or "")
        if expected_substr not in last_result:
            raise AssertionFailure(assertion, last_result, f"Output does not contain '{expected_substr}'")

    def _assert_timing_bound(
        self,
        assertion: ReplayAssertion,
        events: list[RecordedEvent],
        tools: list[RecordedToolCall],
    ) -> None:
        max_ms = assertion.expected
        if not isinstance(max_ms, (int, float)):
            raise AssertionFailure(assertion, None, "expected must be a number (max ms)")

        all_durations = [e.duration_ms for e in events if e.duration_ms is not None]
        all_durations.extend(t.duration_ms for t in tools)

        if any(d > max_ms for d in all_durations):
            worst = max(all_durations)
            raise AssertionFailure(assertion, worst, f"Timing bound exceeded: {worst}ms > {max_ms}ms")

    def _assert_no_regression(
        self,
        assertion: ReplayAssertion,
        events: list[RecordedEvent],
        tools: list[RecordedToolCall],
    ) -> None:
        error_events = [e for e in events if "error" in e.event_type.lower()]
        error_tools = [t for t in tools if t.error is not None]

        if error_events or error_tools:
            errors = [e.event_type for e in error_events] + [t.error for t in error_tools if t.error]
            raise AssertionFailure(assertion, errors, f"Regression detected: {len(errors)} error(s)")

    def _assert_state_snapshot(self, assertion: ReplayAssertion, events: list[RecordedEvent]) -> None:
        if not isinstance(assertion.expected, dict):
            raise AssertionFailure(assertion, None, "expected must be a dict for state snapshot")

        state_events = [e for e in events if e.event_type == "state.snapshot"]
        if not state_events:
            raise AssertionFailure(assertion, None, "No state snapshot events found")

        last_state = state_events[-1].payload
        for key, expected_val in assertion.expected.items():
            actual_val = last_state.get(key)
            if actual_val != expected_val:
                raise AssertionFailure(
                    assertion, last_state,
                    f"State mismatch for '{key}': expected {expected_val}, got {actual_val}",
                )


def compare_with_golden(recording: SessionRecording, golden: GoldenSnapshot) -> list[dict[str, Any]]:
    diffs = []
    recorded_state = {
        "event_count": len(recording.events),
        "tool_call_count": len(recording.tool_calls),
        "decision_count": len(recording.decisions),
        "event_types": sorted(set(e.event_type for e in recording.events)),
        "tool_names": sorted(set(t.tool_name for t in recording.tool_calls)),
    }

    for key, expected in golden.content.items():
        actual = recorded_state.get(key)
        if actual != expected:
            diffs.append({"key": key, "expected": expected, "actual": actual})

    return diffs
