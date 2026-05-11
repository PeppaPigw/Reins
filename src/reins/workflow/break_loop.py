"""Break-loop detection and retrospective trigger.

Identifies when an agent is stuck in a loop (repeated failures, oscillations,
stalls) and triggers structured retrospective capture for context injection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class LoopPattern:
    """Detected loop pattern in agent behavior."""

    pattern_type: str  # "repeated_failure", "oscillation", "stall"
    event_types: tuple[str, ...]
    count: int
    window_seconds: float


@dataclass
class Retrospective:
    """Structured retrospective triggered by loop detection."""

    task_id: str | None
    trigger: LoopPattern
    timestamp: str  # ISO format
    context_summary: str
    attempted_actions: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    learnings: list[str] = field(default_factory=list)
    suggested_next: str | None = None


class BreakLoopDetector:
    """Detects repetitive patterns in agent event streams.

    Monitors event flow for repeated failures, oscillating behavior,
    and stalls, triggering retrospective capture when thresholds are met.
    """

    def __init__(
        self,
        threshold: int = 3,
        window_seconds: float = 300.0,
        patterns: list[str] | None = None,
    ) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._event_buffer: list[tuple[float, str]] = []
        self._patterns = patterns or ["command.failed", "eval.failed", "repair.required"]

    def record_event(
        self, event_type: str, timestamp: float | None = None
    ) -> LoopPattern | None:
        """Add event to buffer and check for patterns.

        Returns a LoopPattern if a loop is detected, None otherwise.
        """
        ts = timestamp if timestamp is not None else time.time()
        self._event_buffer.append((ts, event_type))
        self._prune_buffer(ts)

        # Check all detection strategies
        pattern = self.detect_repeated_failure()
        if pattern:
            return pattern

        pattern = self.detect_oscillation()
        if pattern:
            return pattern

        pattern = self.detect_stall()
        if pattern:
            return pattern

        return None

    def detect_repeated_failure(self) -> LoopPattern | None:
        """Check if same failure event repeated >= threshold times within window."""
        if not self._event_buffer:
            return None

        now = self._event_buffer[-1][0]
        window_start = now - self._window_seconds

        # Count occurrences of each tracked pattern in window
        for pattern_type in self._patterns:
            count = sum(
                1
                for ts, et in self._event_buffer
                if et == pattern_type and ts >= window_start
            )
            if count >= self._threshold:
                return LoopPattern(
                    pattern_type="repeated_failure",
                    event_types=(pattern_type,),
                    count=count,
                    window_seconds=now - window_start,
                )

        return None

    def detect_oscillation(self) -> LoopPattern | None:
        """Check for A->B->A->B pattern (e.g. fix->fail->fix->fail)."""
        if len(self._event_buffer) < 4:
            return None

        now = self._event_buffer[-1][0]
        window_start = now - self._window_seconds

        # Get recent events in window
        recent = [
            et for ts, et in self._event_buffer if ts >= window_start
        ]

        if len(recent) < 4:
            return None

        # Look for alternating pattern in last N events
        for i in range(len(recent) - 3):
            a, b, c, d = recent[i], recent[i + 1], recent[i + 2], recent[i + 3]
            if a == c and b == d and a != b:
                # Count how many full oscillations
                count = 2  # We found at least A->B->A->B
                j = i + 4
                while j + 1 < len(recent):
                    if recent[j] == a and recent[j + 1] == b:
                        count += 1
                        j += 2
                    else:
                        break
                if count >= self._threshold:
                    return LoopPattern(
                        pattern_type="oscillation",
                        event_types=(a, b),
                        count=count,
                        window_seconds=now - window_start,
                    )

        return None

    def detect_stall(self) -> LoopPattern | None:
        """Check if no progress events within window (only failures/retries)."""
        if not self._event_buffer:
            return None

        now = self._event_buffer[-1][0]
        window_start = now - self._window_seconds

        recent = [
            (ts, et) for ts, et in self._event_buffer if ts >= window_start
        ]

        if len(recent) < self._threshold:
            return None

        # If ALL recent events are failure patterns, it's a stall
        failure_set = set(self._patterns)
        all_failures = all(et in failure_set for _, et in recent)

        if all_failures and len(recent) >= self._threshold:
            event_types = tuple(sorted({et for _, et in recent}))
            return LoopPattern(
                pattern_type="stall",
                event_types=event_types,
                count=len(recent),
                window_seconds=now - window_start,
            )

        return None

    def trigger_retrospective(
        self,
        pattern: LoopPattern,
        task_id: str | None = None,
        context: str = "",
    ) -> Retrospective:
        """Create a Retrospective from the detected pattern."""
        # Extract attempted actions from buffer
        attempted = list(dict.fromkeys(et for _, et in self._event_buffer))

        # Identify failure reasons from pattern
        failure_reasons = [
            f"{pattern.pattern_type}: {', '.join(pattern.event_types)} "
            f"repeated {pattern.count} times in {pattern.window_seconds:.0f}s"
        ]

        return Retrospective(
            task_id=task_id,
            trigger=pattern,
            timestamp=datetime.now(UTC).isoformat(),
            context_summary=context or f"Loop detected: {pattern.pattern_type}",
            attempted_actions=attempted,
            failure_reasons=failure_reasons,
        )

    def reset(self) -> None:
        """Clear event buffer."""
        self._event_buffer.clear()

    def format_retrospective(self, retro: Retrospective) -> str:
        """Render retrospective as structured markdown for context injection."""
        lines: list[str] = []
        lines.append("## Retrospective")
        lines.append("")
        lines.append(f"**Trigger:** {retro.trigger.pattern_type}")
        lines.append(f"**Timestamp:** {retro.timestamp}")
        if retro.task_id:
            lines.append(f"**Task:** {retro.task_id}")
        lines.append("")
        lines.append("### Context")
        lines.append("")
        lines.append(retro.context_summary)
        lines.append("")

        if retro.attempted_actions:
            lines.append("### Attempted Actions")
            lines.append("")
            for action in retro.attempted_actions:
                lines.append(f"- {action}")
            lines.append("")

        if retro.failure_reasons:
            lines.append("### Failure Reasons")
            lines.append("")
            for reason in retro.failure_reasons:
                lines.append(f"- {reason}")
            lines.append("")

        if retro.learnings:
            lines.append("### Learnings")
            lines.append("")
            for learning in retro.learnings:
                lines.append(f"- {learning}")
            lines.append("")

        if retro.suggested_next:
            lines.append("### Suggested Next Step")
            lines.append("")
            lines.append(retro.suggested_next)
            lines.append("")

        return "\n".join(lines)

    def _prune_buffer(self, now: float) -> None:
        """Remove events outside the time window."""
        cutoff = now - self._window_seconds
        self._event_buffer = [
            (ts, et) for ts, et in self._event_buffer if ts >= cutoff
        ]
