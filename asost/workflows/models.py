"""Serializable domain models for a resumable book translation run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .states import BookState


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BookIdentity:
    book_id: str
    source_path: str
    title: str = ""
    author: str = ""


@dataclass
class TranslationChunk:
    chunk_id: str
    chapter_id: str
    ordinal: int
    source_text: str
    translation: str = ""
    light_review: Dict[str, Any] = field(default_factory=dict)
    deep_review: Optional[Dict[str, Any]] = None
    revision: Optional[str] = None
    quality: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChapterPlan:
    chapter_id: str
    ordinal: int
    title: str
    chunks: List[TranslationChunk] = field(default_factory=list)
    source: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BookRun:
    identity: BookIdentity
    run_id: str
    state: BookState = BookState.CREATED
    resume_state: Optional[BookState] = None
    extracted: Dict[str, Any] = field(default_factory=dict)
    book_analysis: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    terminology: Dict[str, Any] = field(default_factory=dict)
    chapters: List[ChapterPlan] = field(default_factory=list)
    output_path: Optional[str] = None
    verification: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    history: List[Dict[str, str]] = field(default_factory=list)
