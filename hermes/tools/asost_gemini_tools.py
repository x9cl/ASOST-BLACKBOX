"""Schema-validated Gemini tools used by the ASOST translation workflow.

Gemini is deliberately treated as an untrusted JSON producer here.  A response
is decoded and validated before it can reach another agent.  If validation
fails, Gemini gets exactly one repair request; a second failure is returned as
a structured error rather than leaking malformed output into the workflow.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, ClassVar, Mapping, TypeVar

from tools.registry import registry


SCHEMA_VERSION = "1.0"
_DEFAULT_MODEL = "gemini-2.5-flash"


class SchemaValidationError(ValueError):
    """Raised when a Gemini response does not conform to its output schema."""


@dataclass(frozen=True)
class TranslationResult:
    version: str
    translation: str

    schema_name: ClassVar[str] = "TranslationResult"


@dataclass(frozen=True)
class CritiqueResult:
    version: str
    score: int
    issues: list[str]
    severity: str
    source_span: str
    draft_span: str
    confidence: float

    schema_name: ClassVar[str] = "CritiqueResult"


@dataclass(frozen=True)
class TerminologyResult:
    version: str
    terminology: dict[str, str]

    schema_name: ClassVar[str] = "TerminologyResult"


@dataclass(frozen=True)
class ChapterSummaryResult:
    version: str
    summary: str
    key_points: list[str]

    schema_name: ClassVar[str] = "ChapterSummaryResult"


ResultT = TypeVar(
    "ResultT",
    TranslationResult,
    CritiqueResult,
    TerminologyResult,
    ChapterSummaryResult,
)


def _object(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SchemaValidationError("the response must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, Any], fields: set[str]) -> None:
    missing = fields - value.keys()
    extra = value.keys() - fields
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unknown fields: {', '.join(sorted(extra))}")
        raise SchemaValidationError("; ".join(details))


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SchemaValidationError(f"{field} must be a non-empty string")
    return value


def _version(value: Any) -> str:
    version = _string(value, "version")
    if version != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"version must be {SCHEMA_VERSION!r}, received {version!r}"
        )
    return version


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SchemaValidationError(f"{field} must be an array of strings")
    return value


def _parse_translation(value: Any) -> TranslationResult:
    obj = _object(value)
    _exact_fields(obj, {"version", "translation"})
    return TranslationResult(_version(obj["version"]), _string(obj["translation"], "translation"))


def _parse_critique(value: Any) -> CritiqueResult:
    obj = _object(value)
    fields = {
        "version", "score", "issues", "severity", "source_span",
        "draft_span", "confidence",
    }
    _exact_fields(obj, fields)
    score = obj["score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise SchemaValidationError("score must be an integer between 0 and 100")
    confidence = obj["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise SchemaValidationError("confidence must be a number between 0 and 1")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise SchemaValidationError("confidence must be a number between 0 and 1")
    severity = _string(obj["severity"], "severity").lower()
    if severity not in {"none", "low", "medium", "high", "critical"}:
        raise SchemaValidationError(
            "severity must be one of: none, low, medium, high, critical"
        )
    return CritiqueResult(
        _version(obj["version"]), score, _string_list(obj["issues"], "issues"),
        severity, _string(obj["source_span"], "source_span", allow_empty=True),
        _string(obj["draft_span"], "draft_span", allow_empty=True), confidence,
    )


def _parse_terminology(value: Any) -> TerminologyResult:
    obj = _object(value)
    _exact_fields(obj, {"version", "terminology"})
    terms = obj["terminology"]
    if not isinstance(terms, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in terms.items()
    ):
        raise SchemaValidationError("terminology must be an object of string values")
    return TerminologyResult(_version(obj["version"]), dict(terms))


def _parse_summary(value: Any) -> ChapterSummaryResult:
    obj = _object(value)
    _exact_fields(obj, {"version", "summary", "key_points"})
    return ChapterSummaryResult(
        _version(obj["version"]), _string(obj["summary"], "summary"),
        _string_list(obj["key_points"], "key_points"),
    )


def _invoke_gemini(prompt: str) -> str:
    """Call Gemini's REST API; kept small so tests can inject a fake caller."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required")
    model = os.environ.get("ASOST_GEMINI_MODEL", _DEFAULT_MODEL)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def _decode_json(raw: str) -> Any:
    """Decode JSON, accepting only harmless Markdown JSON fences."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].lower() in {"```", "```json"}:
            text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"invalid JSON: {exc}") from exc


def _typed_error(schema_name: str, message: str) -> str:
    return json.dumps(
        {
            "version": SCHEMA_VERSION,
            "error": {
                "type": "GeminiOutputValidationError",
                "schema": schema_name,
                "message": message,
                "repair_attempted": True,
            },
        },
        ensure_ascii=False,
    )


def _run_validated(
    prompt: str,
    parser: Callable[[Any], ResultT],
    schema_name: str,
    caller: Callable[[str], str] | None = None,
) -> str:
    call = caller or _invoke_gemini
    raw = call(prompt)
    try:
        result = parser(_decode_json(raw))
    except SchemaValidationError as first_error:
        repair_prompt = (
            f"Repair the following output as valid JSON for {schema_name} version "
            f"{SCHEMA_VERSION}. Return JSON only. Validation error: {first_error}\n"
            f"Invalid output:\n{raw}"
        )
        repaired = call(repair_prompt)  # Exactly one repair call.
        try:
            result = parser(_decode_json(repaired))
        except SchemaValidationError as final_error:
            return _typed_error(schema_name, str(final_error))
    return json.dumps(asdict(result), ensure_ascii=False)


def handle_translation(args: Mapping[str, Any], *, caller=None) -> str:
    source_text = _string(args.get("source_text"), "source_text")
    directive = _string(args.get("translation_directive", ""), "translation_directive", allow_empty=True)
    glossary = args.get("glossary", {})
    prompt = (
        f"Translate the source according to the directive and glossary. Return TranslationResult "
        f"version {SCHEMA_VERSION} as JSON only.\nDIRECTIVE: {directive}\n"
        f"GLOSSARY: {json.dumps(glossary, ensure_ascii=False)}\nSOURCE:\n{source_text}"
    )
    return _run_validated(prompt, _parse_translation, TranslationResult.schema_name, caller)


def handle_critique(args: Mapping[str, Any], *, caller=None) -> str:
    # These four inputs intentionally remain distinct so agents cannot conflate
    # source evidence, the proposed translation, instructions, and terminology.
    source = _string(args.get("source_text"), "source_text")
    draft = _string(args.get("draft_text"), "draft_text")
    directive = _string(args.get("translation_directive"), "translation_directive", allow_empty=True)
    glossary = args.get("glossary", {})
    prompt = (
        f"Critique the draft against the source. Return CritiqueResult version {SCHEMA_VERSION} "
        "as JSON only; score is an integer 0..100 and confidence is 0..1.\n"
        f"TRANSLATION DIRECTIVE: {directive}\nGLOSSARY: {json.dumps(glossary, ensure_ascii=False)}\n"
        f"SOURCE TEXT:\n{source}\nDRAFT TEXT:\n{draft}"
    )
    return _run_validated(prompt, _parse_critique, CritiqueResult.schema_name, caller)


def handle_terminology(args: Mapping[str, Any], *, caller=None) -> str:
    source = _string(args.get("source_text"), "source_text")
    prompt = (
        f"Extract source-to-target terminology. Return TerminologyResult version {SCHEMA_VERSION} "
        f"as JSON only.\nSOURCE:\n{source}"
    )
    return _run_validated(prompt, _parse_terminology, TerminologyResult.schema_name, caller)


def handle_chapter_summary(args: Mapping[str, Any], *, caller=None) -> str:
    source = _string(args.get("source_text"), "source_text")
    prompt = (
        f"Summarize this chapter. Return ChapterSummaryResult version {SCHEMA_VERSION} "
        f"as JSON only.\nCHAPTER:\n{source}"
    )
    return _run_validated(prompt, _parse_summary, ChapterSummaryResult.schema_name, caller)


def _register(name: str, description: str, properties: dict[str, Any], required: list[str], handler) -> None:
    registry.register(
        name=name,
        toolset="asost_gemini",
        schema={
            "description": description,
            "parameters": {
                "type": "object", "properties": properties, "required": required,
                "additionalProperties": False,
            },
        },
        handler=lambda args, **kwargs: handler(args),
        emoji="♊",
    )


_TEXT = {"type": "string", "minLength": 1}
_GLOSSARY = {"type": "object", "additionalProperties": {"type": "string"}}

_register(
    "asost_gemini_translate", "Translate text with a versioned TranslationResult.",
    {"source_text": _TEXT, "translation_directive": {"type": "string"}, "glossary": _GLOSSARY},
    ["source_text"], handle_translation,
)
_register(
    "asost_gemini_critique", "Critique a draft with a validated CritiqueResult.",
    {"source_text": _TEXT, "draft_text": _TEXT, "translation_directive": {"type": "string"}, "glossary": _GLOSSARY},
    ["source_text", "draft_text", "translation_directive", "glossary"], handle_critique,
)
_register(
    "asost_gemini_terminology", "Extract a versioned terminology mapping.",
    {"source_text": _TEXT}, ["source_text"], handle_terminology,
)
_register(
    "asost_gemini_chapter_summary", "Summarize a chapter into a validated result.",
    {"source_text": _TEXT}, ["source_text"], handle_chapter_summary,
)
