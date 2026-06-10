from __future__ import annotations

from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


class Direction(str, Enum):
    SEND = "send"
    RECV = "recv"
    CHOICE = "choice"
    OFFER = "offer"
    END = "end"


class MessageSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    direction: Direction
    label: str
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    next_states: tuple[str, ...] = ()


class SessionProtocol(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_id: str = Field(default_factory=_new_ulid)
    name: str
    description: str = ""
    initial_state: str = "start"
    terminal_states: tuple[str, ...] = ("end",)
    transitions: dict[str, tuple[MessageSpec, ...]] = Field(default_factory=dict)


class SessionState(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=_new_ulid)
    protocol_name: str
    current_state: str = "start"
    history: tuple[str, ...] = ()
    is_terminated: bool = False


class ProtocolViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    expected_directions: tuple[Direction, ...] = ()
    expected_labels: tuple[str, ...] = ()
    actual_direction: Direction
    actual_label: str
    current_state: str
    message: str = ""


class SessionTypeError(Exception):
    def __init__(self, violation: ProtocolViolation) -> None:
        self.violation = violation
        super().__init__(violation.message)
