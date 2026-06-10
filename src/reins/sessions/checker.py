from __future__ import annotations

from reins.sessions.types import (
    Direction,
    MessageSpec,
    ProtocolViolation,
    SessionProtocol,
    SessionState,
    SessionTypeError,
)


class SessionChecker:
    """Validates agent communication against session type protocols.

    Ensures agents follow declared communication contracts at runtime,
    catching protocol violations before they cause downstream failures.
    """

    def __init__(self) -> None:
        self._protocols: dict[str, SessionProtocol] = {}
        self._sessions: dict[str, SessionState] = {}

    def register_protocol(self, protocol: SessionProtocol) -> None:
        self._protocols[protocol.name] = protocol

    def begin_session(self, protocol_name: str) -> SessionState:
        protocol = self._protocols.get(protocol_name)
        if not protocol:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        state = SessionState(protocol_name=protocol_name, current_state=protocol.initial_state)
        self._sessions[state.session_id] = state
        return state

    def advance(
        self, session_id: str, direction: Direction, label: str
    ) -> SessionState:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Unknown session: {session_id}")
        if state.is_terminated:
            raise SessionTypeError(ProtocolViolation(
                session_id=session_id,
                actual_direction=direction,
                actual_label=label,
                current_state=state.current_state,
                message=f"Session already terminated at state '{state.current_state}'",
            ))

        protocol = self._protocols[state.protocol_name]
        transitions = protocol.transitions.get(state.current_state, ())

        valid = [t for t in transitions if t.direction == direction and t.label == label]
        if not valid:
            expected_dirs = tuple(t.direction for t in transitions)
            expected_labels = tuple(t.label for t in transitions)
            raise SessionTypeError(ProtocolViolation(
                session_id=session_id,
                expected_directions=expected_dirs,
                expected_labels=expected_labels,
                actual_direction=direction,
                actual_label=label,
                current_state=state.current_state,
                message=(
                    f"Protocol violation in state '{state.current_state}': "
                    f"got {direction.value}({label}), expected one of "
                    f"{[f'{t.direction.value}({t.label})' for t in transitions]}"
                ),
            ))

        transition = valid[0]
        next_state = transition.next_states[0] if transition.next_states else "end"
        is_terminal = next_state in protocol.terminal_states

        new_state = SessionState(
            session_id=session_id,
            protocol_name=state.protocol_name,
            current_state=next_state,
            history=state.history + (f"{direction.value}({label})",),
            is_terminated=is_terminal,
        )
        self._sessions[session_id] = new_state
        return new_state

    def validate_complete(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if not state:
            return False
        protocol = self._protocols[state.protocol_name]
        return state.current_state in protocol.terminal_states

    def get_allowed_actions(self, session_id: str) -> list[tuple[Direction, str]]:
        state = self._sessions.get(session_id)
        if not state or state.is_terminated:
            return []
        protocol = self._protocols[state.protocol_name]
        transitions = protocol.transitions.get(state.current_state, ())
        return [(t.direction, t.label) for t in transitions]

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)
