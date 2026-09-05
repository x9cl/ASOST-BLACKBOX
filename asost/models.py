"""Typed identities and state transitions for the ASOST book workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunState(str, Enum):
    CREATED = "created"
    INGESTING = "ingesting"
    ANALYZED = "analyzed"
    PLANNED = "planned"
    TRANSLATING = "translating"
    QUALITY_REVIEW = "quality_review"
    RECONSTRUCTING = "reconstructing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    RETRYABLE_FAILURE = "retryable_failure"
    PROVIDER_EXHAUSTED = "provider_exhausted"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    CANCELLED = "cancelled"


class SegmentState(str, Enum):
    PENDING = "pending"
    TRANSLATING = "translating"
    REVIEWING = "reviewing"
    REVISING = "revising"
    ACCEPTED = "accepted"
    BEST_EFFORT = "best_effort"
    FAILED = "failed"


RUN_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.INGESTING, RunState.ANALYZED, RunState.CANCELLED},
    RunState.INGESTING: {RunState.ANALYZED, RunState.RETRYABLE_FAILURE,
                         RunState.HUMAN_REVIEW_REQUIRED, RunState.CANCELLED},
    RunState.ANALYZED: {RunState.PLANNED, RunState.RETRYABLE_FAILURE, RunState.CANCELLED},
    RunState.PLANNED: {RunState.TRANSLATING, RunState.CANCELLED},
    RunState.TRANSLATING: {RunState.QUALITY_REVIEW, RunState.RETRYABLE_FAILURE,
                           RunState.PROVIDER_EXHAUSTED, RunState.CANCELLED},
    RunState.QUALITY_REVIEW: {RunState.RECONSTRUCTING, RunState.HUMAN_REVIEW_REQUIRED,
                              RunState.RETRYABLE_FAILURE, RunState.CANCELLED},
    RunState.RECONSTRUCTING: {RunState.VERIFYING, RunState.RETRYABLE_FAILURE,
                              RunState.CANCELLED},
    RunState.VERIFYING: {RunState.COMPLETED, RunState.HUMAN_REVIEW_REQUIRED,
                         RunState.RETRYABLE_FAILURE},
    RunState.RETRYABLE_FAILURE: {RunState.INGESTING, RunState.ANALYZED,
                                 RunState.TRANSLATING,
                                 RunState.RECONSTRUCTING, RunState.CANCELLED},
    RunState.PROVIDER_EXHAUSTED: {RunState.TRANSLATING, RunState.CANCELLED},
    RunState.HUMAN_REVIEW_REQUIRED: {RunState.TRANSLATING, RunState.RECONSTRUCTING,
                                     RunState.CANCELLED},
    RunState.COMPLETED: set(),
    RunState.CANCELLED: set(),
}


@dataclass(frozen=True)
class BookIdentity:
    book_id: str
    source_hash: str
    filename: str

    @classmethod
    def from_bytes(cls, filename: str, content: bytes) -> "BookIdentity":
        digest = hashlib.sha256(content).hexdigest()
        return cls(book_id=f"book_{digest[:16]}", source_hash=digest, filename=filename)


@dataclass(frozen=True)
class RunIdentity:
    book_id: str
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex}")


@dataclass
class TranslationDirective:
    genre: str = "unknown"
    narrative_voice: str = "unknown"
    arabic_register: str = "modern_literary_readable"
    dialogue_style: str = "natural"
    name_policy: str = "arabic_transliteration"
    notes: list[str] = field(default_factory=list)


@dataclass
class Segment:
    segment_id: str
    chapter_id: str
    ordinal: int
    source_text: str
    source_hash: str
    state: SegmentState = SegmentState.PENDING
    translation: str = ""
    score: int | None = None
    revision: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, chapter_id: str, ordinal: int, text: str) -> "Segment":
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return cls(
            segment_id=f"{chapter_id}:seg_{ordinal:04d}:{digest[:12]}",
            chapter_id=chapter_id,
            ordinal=ordinal,
            source_text=text,
            source_hash=digest,
        )

    def to_json(self) -> str:
        payload = asdict(self)
        payload["state"] = self.state.value
        return json.dumps(payload, ensure_ascii=False)
