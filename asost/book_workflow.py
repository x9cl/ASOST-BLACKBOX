"""Typed, strict orchestration for the book-level translation workflow."""

import json
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, TypedDict


class Character(TypedDict):
    name: str
    arabic_name: str
    description: str


class Place(TypedDict):
    name: str
    arabic_name: str
    description: str


class Event(TypedDict):
    chapter_id: str
    summary: str


class Relationship(TypedDict):
    source: str
    target: str
    description: str


class StylePolicy(TypedDict):
    register: str
    narration: str
    dialogue: str
    terminology: str


class TranslationDirective(TypedDict):
    genre: str
    tone: str
    characters: List[Character]
    places: List[Place]
    events: List[Event]
    relationships: List[Relationship]
    style_policy: StylePolicy


class BookContext(TypedDict):
    characters: List[Character]
    places: List[Place]
    events: List[Event]
    relationships: List[Relationship]
    style_policy: StylePolicy


class ChapterContext(BookContext):
    chapter_id: str
    continuity_notes: List[str]


_STRING = {"type": "string"}


def _object(properties: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


CHARACTER_SCHEMA = _object({
    "name": _STRING, "arabic_name": _STRING, "description": _STRING,
})
PLACE_SCHEMA = _object({
    "name": _STRING, "arabic_name": _STRING, "description": _STRING,
})
EVENT_SCHEMA = _object({"chapter_id": _STRING, "summary": _STRING})
RELATIONSHIP_SCHEMA = _object({
    "source": _STRING, "target": _STRING, "description": _STRING,
})
STYLE_POLICY_SCHEMA = _object({
    "register": _STRING,
    "narration": _STRING,
    "dialogue": _STRING,
    "terminology": _STRING,
})

_CONTEXT_FIELDS = {
    "characters": {"type": "array", "items": CHARACTER_SCHEMA},
    "places": {"type": "array", "items": PLACE_SCHEMA},
    "events": {"type": "array", "items": EVENT_SCHEMA},
    "relationships": {"type": "array", "items": RELATIONSHIP_SCHEMA},
    "style_policy": STYLE_POLICY_SCHEMA,
}

TRANSLATION_DIRECTIVE_SCHEMA = _object({
    "genre": _STRING,
    "tone": _STRING,
    **_CONTEXT_FIELDS,
})
BOOK_CONTEXT_SCHEMA = _object(dict(_CONTEXT_FIELDS))
CHAPTER_CONTEXT_SCHEMA = _object({
    "chapter_id": _STRING,
    **_CONTEXT_FIELDS,
    "continuity_notes": {"type": "array", "items": _STRING},
})


def validate_schema(value: Any, schema: Dict[str, Any], path: str = "$") -> None:
    """Validate the small JSON-Schema subset used here, including closed objects."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        allowed = set(schema["properties"])
        missing, extra = allowed - set(value), set(value) - allowed
        if missing:
            raise ValueError(f"{path} missing keys: {sorted(missing)}")
        if extra:
            raise ValueError(f"{path} has undefined keys: {sorted(extra)}")
        for key, child in schema["properties"].items():
            validate_schema(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], f"{path}[{index}]")
    elif kind == "string" and not isinstance(value, str):
        raise ValueError(f"{path} must be a string")


def _typed_reply(raw: str, schema: Dict[str, Any], name: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} did not return one JSON object") from exc
    validate_schema(value, schema)
    return value


def _schema_prompt(task: str, payload: Dict[str, Any], schema: Dict[str, Any]) -> str:
    return json.dumps({
        "task": task,
        "payload": payload,
        "response_schema": schema,
        "response_rules": "Return exactly one JSON object; no undefined keys.",
    }, ensure_ascii=False)


class BookWorkflow:
    """Run adapter once, then context preparation/translation/update per chapter."""

    def __init__(self, chat: Callable[[str, str], str]):
        self._chat = chat

    def run(
        self,
        extracted_book: Dict[str, Any],
        segmenter: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
        accept_chapter: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        # This is deliberately before segmenter(): adaptation consumes extraction once.
        directive = _typed_reply(
            self._chat("book_adapter", _schema_prompt(
                "create_translation_directive", extracted_book,
                TRANSLATION_DIRECTIVE_SCHEMA,
            )),
            TRANSLATION_DIRECTIVE_SCHEMA,
            "book_adapter",
        )
        chapters = segmenter(extracted_book)
        book_context: BookContext = {
            key: deepcopy(directive[key]) for key in _CONTEXT_FIELDS
        }  # type: ignore[assignment]
        results = []

        for index, chapter in enumerate(chapters):
            chapter_id = str(chapter.get("id", index + 1))
            chapter_context = _typed_reply(
                self._chat("context_keeper", _schema_prompt(
                    "prepare_chapter_context",
                    {"chapter": chapter, "book_context": book_context},
                    CHAPTER_CONTEXT_SCHEMA,
                )),
                CHAPTER_CONTEXT_SCHEMA,
                "context_keeper",
            )
            translator_payload = {
                "chapter": chapter,
                "translation_directive": directive,
                "chapter_context": chapter_context,
            }
            translation = self._chat(
                "translator",
                json.dumps(translator_payload, ensure_ascii=False),
            ).strip()
            result = {"chapter_id": chapter_id, "translation": translation}
            accepted = accept_chapter(result) if accept_chapter else True
            result["accepted"] = accepted
            results.append(result)

            if accepted:
                book_context = _typed_reply(
                    self._chat("context_keeper", _schema_prompt(
                        "update_book_context",
                        {
                            "previous_book_context": book_context,
                            "chapter": chapter,
                            "chapter_context": chapter_context,
                            "accepted_translation": translation,
                        },
                        BOOK_CONTEXT_SCHEMA,
                    )),
                    BOOK_CONTEXT_SCHEMA,
                    "context_keeper",
                )  # type: ignore[assignment]

        return {
            "translation_directive": directive,
            "book_context": book_context,
            "chapters": results,
        }
