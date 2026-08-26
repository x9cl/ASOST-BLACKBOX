"""Explicit states and transition rules for the book workflow."""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class BookState(str, Enum):
    CREATED = "CREATED"
    INGESTING = "INGESTING"
    ANALYZED = "ANALYZED"
    PLANNED = "PLANNED"
    TRANSLATING = "TRANSLATING"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    RECONSTRUCTING = "RECONSTRUCTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"

    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PROVIDER_EXHAUSTED = "PROVIDER_EXHAUSTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    CANCELLED = "CANCELLED"


HAPPY_PATH = (
    BookState.CREATED,
    BookState.INGESTING,
    BookState.ANALYZED,
    BookState.PLANNED,
    BookState.TRANSLATING,
    BookState.QUALITY_REVIEW,
    BookState.RECONSTRUCTING,
    BookState.VERIFYING,
    BookState.COMPLETED,
)

FAILURE_STATES = frozenset({
    BookState.RETRYABLE_FAILURE,
    BookState.PROVIDER_EXHAUSTED,
    BookState.HUMAN_REVIEW_REQUIRED,
})

_TRANSITIONS: Dict[BookState, FrozenSet[BookState]] = {
    state: frozenset({HAPPY_PATH[index + 1], *FAILURE_STATES, BookState.CANCELLED})
    for index, state in enumerate(HAPPY_PATH[:-1])
}
_TRANSITIONS[BookState.COMPLETED] = frozenset()
_TRANSITIONS[BookState.CANCELLED] = frozenset()
# A failure is resumable only through the supervisor's recorded checkpoint.
for failure in FAILURE_STATES:
    _TRANSITIONS[failure] = frozenset(HAPPY_PATH[1:-1]) | FAILURE_STATES | {BookState.CANCELLED}


class InvalidStateTransition(ValueError):
    """Raised when code attempts to bypass the workflow contract."""


class BookStateMachine:
    def __init__(self, initial: BookState = BookState.CREATED) -> None:
        self.state = initial

    def can_transition(self, target: BookState) -> bool:
        return target in _TRANSITIONS[self.state]

    def transition(self, target: BookState) -> BookState:
        if not self.can_transition(target):
            raise InvalidStateTransition(f"cannot transition from {self.state.value} to {target.value}")
        self.state = target
        return self.state
