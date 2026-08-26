"""Book-level supervisor that composes the existing ASOST/PF capabilities.

All collaborators are injected tools, making ordering, failure and resume behaviour
observable without duplicating extraction or binding the workflow to one provider.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from .models import BookIdentity, BookRun, ChapterPlan, TranslationChunk, utc_now
from .states import BookState, BookStateMachine, FAILURE_STATES, HAPPY_PATH

Tool = Callable[..., Any]


class ProviderExhaustedError(RuntimeError):
    """All configured translation providers/keys have been exhausted."""


class HumanReviewRequiredError(RuntimeError):
    """The workflow cannot safely make an automatic quality decision."""


class ProfessionalDocumentProcessorAdapter:
    """Lazy adapter over ``assost-main/PF.py::ProfessionalDocumentProcessor``.

    Importing PF is deliberately deferred because PF has heavyweight optional
    dependencies and module-level setup. The extraction implementation remains
    owned by PF; this adapter only invokes its public entry point.
    """

    def __init__(self, pf_path: Optional[Path] = None) -> None:
        self.pf_path = pf_path or Path(__file__).resolve().parents[2] / "assost-main" / "PF.py"
        self._processor = None

    def _load_processor(self):
        if self._processor is None:
            module_name = "asost_legacy_pf"
            module = sys.modules.get(module_name)
            if module is None:
                spec = importlib.util.spec_from_file_location(module_name, self.pf_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot load PF module from {self.pf_path}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            self._processor = module.ProfessionalDocumentProcessor
        return self._processor

    def extract(self, source_path: str) -> Dict[str, Any]:
        return self._load_processor().extract_pdf_with_precision(source_path)


class BookSupervisor:
    """Execute and checkpoint the explicit book state machine.

    Deep criticism is conditional on the light critic decision. The reviser and
    quality gate always run, so accepted drafts still pass through the same final
    quality contract before memory is committed.
    """

    def __init__(
        self,
        *,
        extractor: Any,
        book_adapter: Tool,
        context_keeper: Tool,
        terminology: Tool,
        translator: Tool,
        light_critic: Tool,
        deep_critic: Tool,
        reviser: Tool,
        quality_gate: Tool,
        memory_commit: Tool,
        reconstruct: Tool,
        verify: Tool,
        checkpoint: Optional[Tool] = None,
        chunk_size: int = 4000,
        deep_review_threshold: float = 85,
        legacy_fallback: Optional[Tool] = None,
    ) -> None:
        self.extractor = extractor
        self.tools = {
            "book_adapter": book_adapter, "context_keeper": context_keeper,
            "terminology": terminology, "translator": translator,
            "light_critic": light_critic, "deep_critic": deep_critic,
            "reviser": reviser, "quality_gate": quality_gate,
            "memory_commit": memory_commit, "reconstruct": reconstruct, "verify": verify,
        }
        self.checkpoint = checkpoint or (lambda run: None)
        self.chunk_size = chunk_size
        self.deep_review_threshold = deep_review_threshold
        self.legacy_fallback = legacy_fallback

    def _move(self, run: BookRun, target: BookState) -> None:
        machine = BookStateMachine(run.state)
        machine.transition(target)
        run.state = machine.state
        run.updated_at = utc_now()
        run.history.append({"state": target.value, "at": run.updated_at})
        self.checkpoint(run)

    @staticmethod
    def _identity(source_path: str, extracted: Dict[str, Any]) -> BookIdentity:
        canonical = str(Path(source_path).expanduser().resolve())
        fingerprint = json.dumps({
            "path": canonical, "title": extracted.get("title", ""),
            "author": extracted.get("author", ""), "pages": extracted.get("total_pages", 0),
        }, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return BookIdentity(hashlib.sha256(fingerprint).hexdigest()[:24], canonical,
                            extracted.get("title", ""), extracted.get("author", ""))

    def _plan(self, extracted: Dict[str, Any]) -> list[ChapterPlan]:
        plans = []
        for ci, chapter in enumerate(extracted.get("chapters", [])):
            text = str(chapter.get("content", ""))
            pieces = [text[i:i + self.chunk_size] for i in range(0, len(text), self.chunk_size)] or [""]
            chapter_id = str(chapter.get("id", f"chapter-{ci + 1}"))
            chunks = [TranslationChunk(f"{chapter_id}:chunk-{i + 1}", chapter_id, i, piece)
                      for i, piece in enumerate(pieces)]
            plans.append(ChapterPlan(chapter_id, ci, str(chapter.get("title", "")), chunks, chapter))
        return plans

    def start(self, source_path: str) -> BookRun:
        placeholder = BookIdentity("pending", str(source_path))
        run = BookRun(placeholder, str(uuid.uuid4()))
        return self._execute(run, source_path)

    def resume(self, run: BookRun) -> BookRun:
        if run.state not in FAILURE_STATES or run.resume_state is None:
            raise ValueError("only failed runs with a checkpoint can be resumed")
        self._move(run, run.resume_state)
        run.error = None
        return self._execute(run, run.identity.source_path, resumed=True)

    def cancel(self, run: BookRun) -> BookRun:
        self._move(run, BookState.CANCELLED)
        return run

    def _execute(self, run: BookRun, source_path: str, resumed: bool = False) -> BookRun:
        try:
            if run.state == BookState.CREATED:
                self._move(run, BookState.INGESTING)
            if run.state == BookState.INGESTING:
                run.extracted = self.extractor.extract(source_path)
                run.identity = self._identity(source_path, run.extracted)
                # Identity exists before the first book agent is invoked.
                run.book_analysis = self.tools["book_adapter"](run.identity, run.extracted) or {}
                run.context = self.tools["context_keeper"](run.identity, run.extracted, run.book_analysis) or {}
                run.terminology = self.tools["terminology"](run.identity, run.extracted, run.context) or {}
                self._move(run, BookState.ANALYZED)
            if run.state == BookState.ANALYZED:
                run.chapters = self._plan(run.extracted)
                self._move(run, BookState.PLANNED)
            if run.state == BookState.PLANNED:
                self._move(run, BookState.TRANSLATING)
            if run.state == BookState.TRANSLATING:
                for chapter in run.chapters:
                    for chunk in chapter.chunks:
                        # Re-run an interrupted chunk as a unit; a persisted draft alone
                        # does not imply that criticism/revision finished.
                        chunk.translation = self.tools["translator"](chunk, run) or ""
                        chunk.light_review = self.tools["light_critic"](chunk, run) or {}
                        score = chunk.light_review.get("score")
                        if score is None or float(score) < self.deep_review_threshold:
                            chunk.deep_review = self.tools["deep_critic"](chunk, run) or {}
                        chunk.revision = self.tools["reviser"](chunk, run)
                        if chunk.revision:
                            chunk.translation = chunk.revision
                self._move(run, BookState.QUALITY_REVIEW)
            if run.state == BookState.QUALITY_REVIEW:
                for chapter in run.chapters:
                    for chunk in chapter.chunks:
                        chunk.quality = self.tools["quality_gate"](chunk, run) or {}
                        if chunk.quality.get("accepted") is False:
                            raise HumanReviewRequiredError(f"quality gate rejected {chunk.chunk_id}")
                        self.tools["memory_commit"](chunk, run)
                self._move(run, BookState.RECONSTRUCTING)
            if run.state == BookState.RECONSTRUCTING:
                run.output_path = self.tools["reconstruct"](run)
                self._move(run, BookState.VERIFYING)
            if run.state == BookState.VERIFYING:
                run.verification = self.tools["verify"](run) or {}
                if run.verification.get("valid") is False:
                    raise HumanReviewRequiredError("final verification failed")
                self._move(run, BookState.COMPLETED)
            return run
        except Exception as exc:
            resume = run.state if run.state in HAPPY_PATH[1:-1] else BookState.INGESTING
            run.resume_state = resume
            run.error = str(exc)
            failure = (BookState.PROVIDER_EXHAUSTED if isinstance(exc, ProviderExhaustedError)
                       else BookState.HUMAN_REVIEW_REQUIRED if isinstance(exc, HumanReviewRequiredError)
                       else BookState.RETRYABLE_FAILURE)
            self._move(run, failure)
            return run

    def run_legacy_fallback(self, source_path: str, output_dir: str, **kwargs: Any) -> Any:
        """Explicit opt-in bridge to ``MasterTranslationSystem.process_complete_book``.

        It is intentionally not automatic: callers retain the legacy path until
        parity tests approve switching production traffic to this supervisor.
        """
        if self.legacy_fallback is None:
            raise RuntimeError("legacy fallback was not configured")
        return self.legacy_fallback(source_path, output_dir, **kwargs)
