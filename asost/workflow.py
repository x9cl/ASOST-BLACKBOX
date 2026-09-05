"""Hermes-driven book workflow with durable checkpoints and quality gates."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from asost.agent_runner import build_agent
from asost.config import settings
from asost.models import (
    BookIdentity,
    RunIdentity,
    RunState,
    Segment,
    SegmentState,
    TranslationDirective,
)
from asost.store import ASOSTStore


AgentFactory = Callable[..., Any]


def split_text(text: str, max_chars: int = 4000) -> list[str]:
    """Split without discarding text, preferring paragraph boundaries."""
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[str] = []
    current = ""
    for part in paragraphs:
        if len(current) + len(part) <= max_chars:
            current += part
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(part) > max_chars:
            split_at = part.rfind(" ", 0, max_chars)
            split_at = split_at if split_at > max_chars // 2 else max_chars
            chunks.append(part[:split_at])
            part = part[split_at:]
        current = part
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _first_json(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for pos, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[pos:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def deterministic_quality(source: str, translation: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not translation.strip():
        issues.append({"type": "empty", "severity": "critical"})
        return issues
    english = re.findall(r"\b[A-Za-z]{4,}\b", translation)
    if len(english) > max(2, len(source.split()) // 30):
        issues.append({"type": "foreign_content", "severity": "high"})
    ratio = len(translation) / max(1, len(source))
    if ratio < 0.35:
        issues.append({"type": "possible_omission", "severity": "high"})
    if ratio > 3.5:
        issues.append({"type": "possible_expansion", "severity": "medium"})
    return issues


def place_chapter_images(chapter: dict[str, Any], translated: str,
                         illustrations: list[dict[str, Any]]) -> str:
    """Place extracted image markers by their page ratio inside a chapter."""
    start = int(chapter.get("start_page", 0))
    end = int(chapter.get("end_page", start))
    images = sorted(
        (item for item in illustrations if start <= int(item.get("page", -1)) <= end),
        key=lambda item: int(item["page"]),
    )
    if not images:
        return translated
    paragraphs = [part for part in translated.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [""]
    span = max(1, end - start + 1)
    insertions: list[tuple[int, str]] = []
    for image in images:
        ratio = (int(image["page"]) - start) / span
        index = min(len(paragraphs), max(0, round(ratio * len(paragraphs))))
        insertions.append((index, f"[IMG:{image['name']}|{image.get('class', 'illustration')}]"))
    for index, marker in reversed(insertions):
        paragraphs.insert(index, marker)
    return "\n\n".join(paragraphs)


class BookSupervisor:
    """Coordinates ASOST roles while Hermes remains the agent runtime."""

    def __init__(self, store: ASOSTStore, agent_factory: AgentFactory = build_agent,
                 accept_threshold: int = 85, max_revisions: int = 3,
                 max_agent_calls: int | None = None):
        self.store = store
        self.agent_factory = agent_factory
        self.accept_threshold = accept_threshold
        self.max_revisions = max_revisions
        self.max_agent_calls = max_agent_calls or settings.max_agent_calls_per_run
        self._agents: dict[tuple[str, str, str], Any] = {}
        self._call_counts: dict[str, int] = {}

    def _agent(self, role: str, book_id: str, run_id: str):
        key = (role, book_id, run_id)
        if key not in self._agents:
            self._agents[key] = self.agent_factory(role, book_id=book_id, run_id=run_id)
        return self._agents[key]

    def _chat(self, role: str, book_id: str, run_id: str, prompt: str) -> str:
        count = self._call_counts.get(run_id, 0) + 1
        if count > self.max_agent_calls:
            raise RuntimeError("ASOST agent-call budget exhausted")
        self._call_counts[run_id] = count
        response = self._agent(role, book_id, run_id).chat(prompt)
        return response if isinstance(response, str) else str(response)

    def start(self, filename: str, content: bytes, owner_id: str) -> tuple[BookIdentity, RunIdentity]:
        book = BookIdentity.from_bytes(filename, content)
        run = RunIdentity(book.book_id)
        self.store.create_run(book, run, owner_id)
        return book, run

    def process_chapters(self, book: BookIdentity, run: RunIdentity,
                         chapters: list[dict[str, str]], *, finalize: bool = True) -> dict[str, Any]:
        try:
            self.store.transition(run.run_id, RunState.ANALYZED)
            sample = "\n\n".join(ch.get("content", "")[:1500] for ch in chapters[:3])
            adapter_raw = self._chat(
                "book_adapter", book.book_id, run.run_id,
                "Analyze this book and return JSON with genre, narrative_voice, "
                "arabic_register, dialogue_style, name_policy, notes.\n\n" + sample,
            )
            adapter = _first_json(adapter_raw)
            allowed = set(TranslationDirective.__dataclass_fields__)
            directive = TranslationDirective(**{k: v for k, v in adapter.items() if k in allowed})
            self.store.memory_put(book.book_id, "book", "translation_directive", asdict(directive))

            context_raw = self._chat(
                "context_keeper", book.book_id, run.run_id,
                "Extract initial characters, places, terminology and unresolved "
                "references as JSON. Use Gemini terminology tool if useful.\n\n" + sample,
            )
            self.store.memory_put(book.book_id, "book", "initial_context", _first_json(context_raw))
            terms_raw = self._chat(
                "terminologist", book.book_id, run.run_id,
                "Build the initial canonical glossary as JSON.\n\n" + sample,
            )
            self.store.memory_put(book.book_id, "terminology", "canonical", _first_json(terms_raw))
            plan_raw = self._chat(
                "translation_planner", book.book_id, run.run_id,
                "Return a JSON translation plan with risks and context policy.\n\n" + sample,
            )
            self.store.memory_put(book.book_id, "book", "translation_plan", _first_json(plan_raw))
            self.store.transition(run.run_id, RunState.PLANNED)
            self.store.transition(run.run_id, RunState.TRANSLATING)

            accepted: list[Segment] = []
            unresolved: list[Segment] = []
            for chapter_no, chapter in enumerate(chapters, 1):
                chapter_id = chapter.get("id") or f"chapter_{chapter_no:04d}"
                for ordinal, source in enumerate(split_text(chapter.get("content", "")), 1):
                    segment = Segment.create(chapter_id, ordinal, source)
                    cached = self.store.accepted_translation(run.run_id, segment.segment_id)
                    if cached is not None:
                        segment.translation = cached
                        segment.state = SegmentState.ACCEPTED
                        accepted.append(segment)
                        continue
                    self._process_segment(book, run, directive, segment)
                    self.store.save_segment(run.run_id, segment)
                    if segment.state == SegmentState.ACCEPTED:
                        accepted.append(segment)
                    else:
                        unresolved.append(segment)
                chapter_segments = [
                    item for item in accepted if item.chapter_id == chapter_id
                ]
                chapter_unresolved = [
                    item for item in unresolved if item.chapter_id == chapter_id
                ]
                if chapter_segments and not chapter_unresolved:
                    chapter_translation = "\n\n".join(
                        item.translation for item in chapter_segments
                    )
                    summary = _first_json(self._chat(
                        "context_keeper", book.book_id, run.run_id,
                        "Commit a JSON continuity summary for the accepted chapter. "
                        "Include events, characters, relationships, locations and "
                        "unresolved references.\n\n" + chapter_translation,
                    ))
                    self.store.memory_put(
                        book.book_id, "chapters", f"{chapter_id}:summary", summary
                    )
                    terminology = _first_json(self._chat(
                        "terminologist", book.book_id, run.run_id,
                        "Return JSON terminology learned from this accepted chapter. "
                        "Do not replace approved canonical forms silently.\n\n" +
                        chapter_translation,
                    ))
                    self.store.memory_put(
                        book.book_id, "terminology", f"{chapter_id}:candidates", terminology
                    )

            self.store.transition(run.run_id, RunState.QUALITY_REVIEW)
            if unresolved:
                self.store.transition(
                    run.run_id, RunState.HUMAN_REVIEW_REQUIRED,
                    {"unresolved_segments": [item.segment_id for item in unresolved]},
                )
                return {
                    "book_id": book.book_id,
                    "run_id": run.run_id,
                    "state": RunState.HUMAN_REVIEW_REQUIRED.value,
                    "directive": asdict(directive),
                    "segments": [json.loads(seg.to_json()) for seg in accepted + unresolved],
                }
            final_state = RunState.QUALITY_REVIEW
            if finalize:
                self.store.transition(run.run_id, RunState.RECONSTRUCTING)
                self.store.transition(run.run_id, RunState.VERIFYING)
                self.store.transition(run.run_id, RunState.COMPLETED,
                                      {"accepted_segments": len(accepted)})
                final_state = RunState.COMPLETED
            return {
                "book_id": book.book_id,
                "run_id": run.run_id,
                "state": final_state.value,
                "directive": asdict(directive),
                "segments": [json.loads(seg.to_json()) for seg in accepted],
            }
        except Exception as exc:
            self.store.transition(run.run_id, RunState.RETRYABLE_FAILURE,
                                  error_code=type(exc).__name__)
            raise

    def process_pdf(self, pdf_path: str | Path, output_path: str | Path,
                    owner_id: str) -> dict[str, Any]:
        """Run extraction, agents, composition, and verification for one PDF."""
        from asost.document_tools import compose_docx, extract_pdf, verify_docx

        path = Path(pdf_path)
        content = path.read_bytes()
        book, run = self.start(path.name, content, owner_id)
        self.store.transition(run.run_id, RunState.INGESTING)
        try:
            structure = extract_pdf(path)
        except Exception as exc:
            self.store.transition(
                run.run_id, RunState.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
            )
            raise
        chapters = structure.get("chapters") or []
        if not chapters:
            self.store.transition(
                run.run_id, RunState.HUMAN_REVIEW_REQUIRED,
                {"reason": "no_chapters_extracted"},
            )
            raise ValueError("No chapters were extracted from the PDF")
        result = self.process_chapters(book, run, chapters, finalize=False)
        if result["state"] == RunState.HUMAN_REVIEW_REQUIRED.value:
            return result

        translated_by_chapter: dict[str, list[str]] = {}
        for segment in result["segments"]:
            translated_by_chapter.setdefault(segment["chapter_id"], []).append(
                segment["translation"]
            )
        output_chapters = []
        illustrations = structure.get("illustrations") or []
        assigned_names = {
            name for chapter in chapters for name in (chapter.get("images_map") or {})
        }
        unassigned = [
            item for item in sorted(illustrations, key=lambda value: int(value["page"]))
            if item["name"] not in assigned_names
        ]
        for index, chapter in enumerate(chapters, 1):
            chapter_id = chapter.get("id") or f"chapter_{index:04d}"
            translated = "\n\n".join(translated_by_chapter.get(chapter_id, []))
            translated = place_chapter_images(chapter, translated, illustrations)
            images_map = dict(chapter.get("images_map") or {})
            if index == 1 and unassigned:
                markers = []
                for image in unassigned:
                    images_map[image["name"]] = image["path"]
                    markers.append(
                        f"[IMG:{image['name']}|{image.get('class', 'illustration')}]"
                    )
                translated = "\n\n".join(markers + [translated])
            output_chapters.append({
                **chapter,
                "images_map": images_map,
                "translated_content": translated,
            })
        self.store.transition(run.run_id, RunState.RECONSTRUCTING)
        try:
            produced = compose_docx(
                output_chapters, output_path,
                structure.get("title") or path.stem,
                structure.get("author") or "Unknown Author",
            )
        except Exception as exc:
            self.store.transition(
                run.run_id, RunState.RETRYABLE_FAILURE,
                error_code=type(exc).__name__,
            )
            raise
        self.store.transition(run.run_id, RunState.VERIFYING)
        verification = verify_docx(produced, len(output_chapters), 0)
        checks = verification.get("checks", {})
        if checks and not all(checks.values()):
            self.store.transition(
                run.run_id, RunState.HUMAN_REVIEW_REQUIRED,
                {"verification": verification},
            )
            result["state"] = RunState.HUMAN_REVIEW_REQUIRED.value
            result["verification"] = verification
            return result
        self.store.transition(
            run.run_id, RunState.COMPLETED,
            {"output_path": str(produced), "verification": verification},
        )
        result.update(
            state=RunState.COMPLETED.value,
            output_path=str(produced),
            verification=verification,
        )
        return result

    def _process_segment(self, book: BookIdentity, run: RunIdentity,
                         directive: TranslationDirective, segment: Segment) -> None:
        context = self.store.memory_get(book.book_id, "book", "rolling_context", "")
        segment.state = SegmentState.TRANSLATING
        translation = self._chat(
            "translator", book.book_id, run.run_id,
            "Translate SOURCE to Arabic. You may call the Gemini translation tool "
            "once if it improves fidelity. Output Arabic only.\n"
            f"DIRECTIVE:{json.dumps(asdict(directive), ensure_ascii=False)}\n"
            f"CONTEXT:{context[-1500:]}\nSOURCE:{segment.source_text}",
        ).strip()
        segment.translation = translation

        for revision in range(self.max_revisions + 1):
            segment.state = SegmentState.REVIEWING
            deterministic = deterministic_quality(segment.source_text, segment.translation)
            critic = _first_json(self._chat(
                "critic_light", book.book_id, run.run_id,
                "Return JSON only: {\"score\":0-100,\"issues\":[]}. Review the "
                "complete source and translation.\nSOURCE:\n" + segment.source_text +
                "\nTRANSLATION:\n" + segment.translation,
            ))
            score = critic.get("score")
            segment.score = int(score) if isinstance(score, (int, float)) else 0
            segment.issues = deterministic + (critic.get("issues") or [])
            gate = _first_json(self._chat(
                "quality_gate", book.book_id, run.run_id,
                "Return JSON decision. Deterministic issues: " +
                json.dumps(deterministic) + f"\nCritic score: {segment.score}",
            ))
            if (segment.score >= self.accept_threshold and not deterministic
                    and gate.get("decision") == "accept"):
                segment.state = SegmentState.ACCEPTED
                segment.revision = revision
                self.store.memory_put(
                    book.book_id, "book", "rolling_context", segment.translation[-2500:]
                )
                return
            if revision >= self.max_revisions:
                segment.state = SegmentState.BEST_EFFORT
                segment.revision = revision
                return
            deep = self._chat(
                "critic_deep", book.book_id, run.run_id,
                "Return evidence-based JSON issues for the complete pair.\nSOURCE:\n" +
                segment.source_text + "\nTRANSLATION:\n" + segment.translation,
            )
            segment.state = SegmentState.REVISING
            segment.translation = self._chat(
                "reviser", book.book_id, run.run_id,
                "Correct the draft using all issues. Return Arabic only.\nSOURCE:\n" +
                segment.source_text + "\nDRAFT:\n" + segment.translation +
                "\nISSUES:\n" + deep,
            ).strip()
