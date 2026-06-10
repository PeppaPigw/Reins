"""Testing utilities: replay-based regression testing and coverage configuration."""

from reins.testing.recorder import SessionRecorder
from reins.testing.replay_types import (
    AssertionKind,
    GoldenSnapshot,
    Mutation,
    MutationKind,
    RecordedDecision,
    RecordedEvent,
    RecordedToolCall,
    RecordingMode,
    ReplayAssertion,
    ReplayConfig,
    ReplayMode,
    ReplayResult,
    SessionRecording,
)
from reins.testing.replayer import SessionReplayer, compare_with_golden

__all__ = [
    "AssertionKind",
    "GoldenSnapshot",
    "Mutation",
    "MutationKind",
    "RecordedDecision",
    "RecordedEvent",
    "RecordedToolCall",
    "RecordingMode",
    "ReplayAssertion",
    "ReplayConfig",
    "ReplayMode",
    "ReplayResult",
    "SessionRecorder",
    "SessionRecording",
    "SessionReplayer",
    "compare_with_golden",
]
