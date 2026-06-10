from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from reins.session.types import (
    ConversationTurn,
    MigrationManifest,
    MigrationStrategy,
    ResumeResult,
    SessionContext,
    SessionState,
    SessionStatus,
    SuspendedSession,
    SuspendReason,
)


class SessionContinuityEngine:
    """Manages session lifecycle: suspend, resume, migrate across machines.

    Provides deterministic session serialization with integrity verification,
    enabling agents to pause work and resume later with full state preservation.
    """

    def __init__(self, max_suspended: int = 100, default_ttl_hours: int = 72) -> None:
        self._active: dict[str, SessionState] = {}
        self._suspended: dict[str, SuspendedSession] = {}
        self._max_suspended = max_suspended
        self._default_ttl_hours = default_ttl_hours

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def suspended_count(self) -> int:
        return len(self._suspended)

    def create_session(self, agent_id: str, context: SessionContext | None = None) -> SessionState:
        session = SessionState(
            agent_id=agent_id,
            context=context or SessionContext(),
        )
        self._active[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionState | None:
        return self._active.get(session_id)

    def add_turn(self, session_id: str, role: str, content: str, tool_calls: tuple[dict[str, Any], ...] = ()) -> SessionState:
        session = self._active.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found or not active")

        turn = ConversationTurn(role=role, content=content, tool_calls=tool_calls)
        updated = SessionState(
            session_id=session.session_id,
            agent_id=session.agent_id,
            status=session.status,
            context=session.context,
            conversation=session.conversation + (turn,),
            task_stack=session.task_stack,
            memory_refs=session.memory_refs,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=datetime.now(UTC),
            version=session.version + 1,
        )
        self._active[session_id] = updated
        return updated

    def update_context(self, session_id: str, context: SessionContext) -> SessionState:
        session = self._active.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found or not active")

        updated = SessionState(
            session_id=session.session_id,
            agent_id=session.agent_id,
            status=session.status,
            context=context,
            conversation=session.conversation,
            task_stack=session.task_stack,
            memory_refs=session.memory_refs,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=datetime.now(UTC),
            version=session.version + 1,
        )
        self._active[session_id] = updated
        return updated

    def push_task(self, session_id: str, task_id: str) -> SessionState:
        session = self._active.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found or not active")

        updated = SessionState(
            session_id=session.session_id,
            agent_id=session.agent_id,
            status=session.status,
            context=session.context,
            conversation=session.conversation,
            task_stack=session.task_stack + (task_id,),
            memory_refs=session.memory_refs,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=datetime.now(UTC),
            version=session.version + 1,
        )
        self._active[session_id] = updated
        return updated

    def pop_task(self, session_id: str) -> tuple[SessionState, str | None]:
        session = self._active.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found or not active")

        if not session.task_stack:
            return session, None

        popped = session.task_stack[-1]
        updated = SessionState(
            session_id=session.session_id,
            agent_id=session.agent_id,
            status=session.status,
            context=session.context,
            conversation=session.conversation,
            task_stack=session.task_stack[:-1],
            memory_refs=session.memory_refs,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=datetime.now(UTC),
            version=session.version + 1,
        )
        self._active[session_id] = updated
        return updated, popped

    def suspend(self, session_id: str, reason: SuspendReason = SuspendReason.USER_REQUEST, resume_hint: str = "") -> SuspendedSession:
        session = self._active.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found or not active")

        suspended_state = SessionState(
            session_id=session.session_id,
            agent_id=session.agent_id,
            status=SessionStatus.SUSPENDED,
            context=session.context,
            conversation=session.conversation,
            task_stack=session.task_stack,
            memory_refs=session.memory_refs,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=datetime.now(UTC),
            suspended_at=datetime.now(UTC),
            version=session.version + 1,
        )

        checksum = self._compute_checksum(suspended_state)

        suspended = SuspendedSession(
            session_state=suspended_state,
            reason=reason,
            resume_hint=resume_hint,
            ttl_hours=self._default_ttl_hours,
            checksum=checksum,
        )

        del self._active[session_id]
        self._suspended[session_id] = suspended
        self._evict_expired()

        return suspended

    def resume(self, session_id: str) -> ResumeResult:
        suspended = self._suspended.get(session_id)
        if not suspended:
            return ResumeResult(
                session_id=session_id,
                success=False,
                warnings=("Session not found in suspended sessions",),
            )

        if self._is_expired(suspended):
            del self._suspended[session_id]
            return ResumeResult(
                session_id=session_id,
                success=False,
                warnings=("Session has expired",),
            )

        current_checksum = self._compute_checksum(suspended.session_state)
        warnings: list[str] = []
        if current_checksum != suspended.checksum:
            warnings.append("Checksum mismatch — state may be corrupted")

        resumed_state = SessionState(
            session_id=suspended.session_state.session_id,
            agent_id=suspended.session_state.agent_id,
            status=SessionStatus.RESUMED,
            context=suspended.session_state.context,
            conversation=suspended.session_state.conversation,
            task_stack=suspended.session_state.task_stack,
            memory_refs=suspended.session_state.memory_refs,
            metadata=suspended.session_state.metadata,
            created_at=suspended.session_state.created_at,
            updated_at=datetime.now(UTC),
            version=suspended.session_state.version + 1,
        )

        self._active[session_id] = resumed_state
        del self._suspended[session_id]

        return ResumeResult(
            session_id=session_id,
            success=True,
            restored_turns=len(resumed_state.conversation),
            restored_context=True,
            warnings=tuple(warnings),
        )

    def prepare_migration(self, session_id: str, target_host: str, source_host: str = "local", strategy: MigrationStrategy = MigrationStrategy.FULL_TRANSFER) -> MigrationManifest:
        session = self._active.get(session_id) or (
            self._suspended[session_id].session_state if session_id in self._suspended else None
        )
        if not session:
            raise KeyError(f"Session '{session_id}' not found")

        serialized = self.serialize(session_id)
        size = len(serialized.encode("utf-8"))

        return MigrationManifest(
            source_host=source_host,
            target_host=target_host,
            session_id=session_id,
            strategy=strategy,
            state_size_bytes=size,
            chunks_total=max(1, size // (64 * 1024)),
        )

    def serialize(self, session_id: str) -> str:
        session = self._active.get(session_id)
        if session:
            return session.model_dump_json()

        suspended = self._suspended.get(session_id)
        if suspended:
            return suspended.session_state.model_dump_json()

        raise KeyError(f"Session '{session_id}' not found")

    def deserialize(self, data: str) -> SessionState:
        state = SessionState.model_validate_json(data)
        self._active[state.session_id] = state
        return state

    def terminate(self, session_id: str) -> bool:
        if session_id in self._active:
            del self._active[session_id]
            return True
        if session_id in self._suspended:
            del self._suspended[session_id]
            return True
        return False

    def list_suspended(self) -> list[SuspendedSession]:
        self._evict_expired()
        return list(self._suspended.values())

    def _compute_checksum(self, state: SessionState) -> str:
        data = state.model_dump_json().encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:16]

    def _is_expired(self, suspended: SuspendedSession) -> bool:
        expiry = suspended.suspended_at + timedelta(hours=suspended.ttl_hours)
        return datetime.now(UTC) > expiry

    def _evict_expired(self) -> None:
        expired = [sid for sid, s in self._suspended.items() if self._is_expired(s)]
        for sid in expired:
            del self._suspended[sid]
