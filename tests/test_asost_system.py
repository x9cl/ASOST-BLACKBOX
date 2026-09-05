"""Offline system tests for state, role ordering, quality, and Gemini contracts."""

from __future__ import annotations

import inspect
import importlib
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
HERMES = ROOT / "hermes"
if str(HERMES) not in sys.path:
    sys.path.insert(0, str(HERMES))

from asost.models import BookIdentity, RunIdentity, RunState, Segment  # noqa: E402
from asost.store import ASOSTStore  # noqa: E402
from asost.workflow import (  # noqa: E402
    BookSupervisor, deterministic_quality, place_chapter_images, split_text,
)
asost_gemini_tools = importlib.import_module("tools.asost_gemini_tools")
asost_tools = importlib.import_module("tools.asost_tools")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ASOSTStore(Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_books_runs_and_memory_are_isolated(self):
        first = BookIdentity.from_bytes("first.pdf", b"first")
        second = BookIdentity.from_bytes("second.pdf", b"second")
        first_run, second_run = RunIdentity(first.book_id), RunIdentity(second.book_id)
        self.store.create_run(first, first_run, "owner-a")
        self.store.create_run(second, second_run, "owner-b")
        self.store.memory_put(first.book_id, "terminology", "hero", "البطل الأول")
        self.store.memory_put(second.book_id, "terminology", "hero", "البطل الثاني")
        self.assertEqual(
            self.store.memory_get(first.book_id, "terminology", "hero"), "البطل الأول"
        )
        self.assertIsNone(self.store.get_run(first_run.run_id, "owner-b"))

    def test_concurrent_memory_updates_do_not_corrupt_database(self):
        book = BookIdentity.from_bytes("book.pdf", b"book")
        run = RunIdentity(book.book_id)
        self.store.create_run(book, run, "owner")
        threads = [
            threading.Thread(
                target=self.store.memory_put,
                args=(book.book_id, "test", f"key-{index}", index),
            )
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.store.memory_summary(book.book_id), {"test": 20})

    def test_accepted_cache_is_scoped_to_run_and_source_identity(self):
        book = BookIdentity.from_bytes("book.pdf", b"book")
        run = RunIdentity(book.book_id)
        other_run = RunIdentity(book.book_id)
        self.store.create_run(book, run, "owner")
        self.store.create_run(book, other_run, "owner")
        segment = Segment.create("chapter_1", 1, "source")
        segment.translation = "ترجمة"
        segment.state = segment.state.ACCEPTED
        self.store.save_segment(run.run_id, segment)
        self.assertEqual(
            self.store.accepted_translation(run.run_id, segment.segment_id), "ترجمة"
        )
        self.assertIsNone(
            self.store.accepted_translation(other_run.run_id, segment.segment_id)
        )

    def test_api_jobs_are_persistent_owned_and_pruned_safely(self):
        self.store.create_api_job("job-1", "owner-a", {"page_num": 1}, max_jobs=1)
        self.assertIsNone(self.store.get_api_job("job-1", "owner-b"))
        with self.assertRaises(OverflowError):
            self.store.create_api_job("job-2", "owner-a", {}, max_jobs=1)
        self.store.update_api_job("job-1", "done", result={"ok": True})
        self.store.create_api_job("job-2", "owner-a", {"page_num": 2}, max_jobs=1)
        self.assertIsNone(self.store.get_api_job("job-1", "owner-a"))
        reopened = ASOSTStore(Path(self.tmp.name) / "state.db")
        persisted = reopened.get_api_job("job-2", "owner-a")
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted["status"], "queued")


class _FakeAgent:
    def __init__(self, role, calls, low_quality=False):
        self.role = role
        self.calls = calls
        self.low_quality = low_quality

    def chat(self, prompt):
        self.calls.append((self.role, prompt))
        if self.role == "book_adapter":
            return json.dumps({"genre": "novel", "narrative_voice": "first_person"})
        if self.role in {"context_keeper", "terminologist", "translation_planner"}:
            return "{}"
        if self.role == "translator":
            return ("هذه ترجمة عربية أدبية كاملة تحافظ على جميع تفاصيل النص الأصلي "
                    "وحواره وسرده. " * 5)
        if self.role == "critic_light":
            return json.dumps({"score": 20 if self.low_quality else 95, "issues": []})
        if self.role == "quality_gate":
            return json.dumps({"decision": "revise" if self.low_quality else "accept"})
        if self.role == "critic_deep":
            return json.dumps({"issues": [{"type": "style", "severity": "medium"}]})
        if self.role == "reviser":
            return "هذه ترجمة عربية مراجعة لكنها لا تزال بحاجة إلى قرار جودة موثق من النظام."
        raise AssertionError(self.role)


class _FailSecondTranslator(_FakeAgent):
    translations = 0

    def chat(self, prompt):
        if self.role == "translator":
            type(self).translations += 1
            if type(self).translations == 2:
                raise ConnectionError("simulated interruption")
        return super().chat(prompt)


class WorkflowTests(unittest.TestCase):
    def _run(self, low_quality=False):
        temp = tempfile.TemporaryDirectory()
        store = ASOSTStore(Path(temp.name) / "state.db")
        calls = []

        def factory(role, **_identity):
            return _FakeAgent(role, calls, low_quality)

        supervisor = BookSupervisor(store, factory, max_revisions=2)
        source = (
            "This is a complete narrative paragraph with enough content to exercise "
            "the translation quality workflow without relying on a remote model."
        )
        book, run = supervisor.start("book.pdf", source.encode(), "owner")
        result = supervisor.process_chapters(
            book, run, [{"id": "chapter_1", "content": source}]
        )
        return temp, store, calls, run, result

    def test_complete_role_order_and_acceptance(self):
        temp, store, calls, run, result = self._run()
        self.addCleanup(temp.cleanup)
        roles = [role for role, _ in calls]
        self.assertEqual(roles[:4], [
            "book_adapter", "context_keeper", "terminologist", "translation_planner"
        ])
        self.assertIn("translator", roles)
        self.assertIn("critic_light", roles)
        self.assertIn("quality_gate", roles)
        self.assertNotIn("critic_deep", roles)
        self.assertEqual(result["state"], RunState.COMPLETED.value)
        persisted = store.get_run(run.run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted["state"], RunState.COMPLETED.value)

    def test_failed_quality_gate_requires_human_review(self):
        temp, store, calls, run, result = self._run(low_quality=True)
        self.addCleanup(temp.cleanup)
        roles = [role for role, _ in calls]
        self.assertIn("critic_deep", roles)
        self.assertIn("reviser", roles)
        self.assertEqual(result["state"], RunState.HUMAN_REVIEW_REQUIRED.value)
        persisted = store.get_run(run.run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted["state"], RunState.HUMAN_REVIEW_REQUIRED.value)

    def test_agent_call_budget_stops_unbounded_work(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = ASOSTStore(Path(temp.name) / "state.db")
        calls = []
        supervisor = BookSupervisor(
            store,
            lambda role, **_identity: _FakeAgent(role, calls),
            max_agent_calls=1,
        )
        book, run = supervisor.start("book.pdf", b"book", "owner")
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            supervisor.process_chapters(
                book, run, [{"id": "chapter_1", "content": "source " * 30}]
            )
        persisted = store.get_run(run.run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted["state"], RunState.RETRYABLE_FAILURE.value)

    def test_pdf_workflow_reaches_verified_output_with_deterministic_adapters(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        pdf = root / "book.pdf"
        output = root / "translated.docx"
        pdf.write_bytes(b"%PDF-offline-fixture")
        store = ASOSTStore(root / "state.db")
        calls = []
        supervisor = BookSupervisor(
            store, lambda role, **_identity: _FakeAgent(role, calls)
        )

        def fake_compose(chapters, output_path, _title, _author, _toc=None):
            self.assertTrue(chapters[0]["translated_content"])
            Path(output_path).write_bytes(b"docx")
            return str(output_path)

        with patch("asost.document_tools.extract_pdf", return_value={
            "title": "Book", "author": "Author",
            "chapters": [{"id": "chapter_1", "title": "One",
                          "content": "source narrative " * 20}],
        }), patch("asost.document_tools.compose_docx", side_effect=fake_compose), patch(
            "asost.document_tools.verify_docx",
            return_value={"checks": {"opens": True, "chapters": True}},
        ):
            result = supervisor.process_pdf(pdf, output, "owner")
        self.assertEqual(result["state"], RunState.COMPLETED.value)
        self.assertEqual(result["output_path"], str(output))
        self.assertTrue(output.exists())

    def test_interrupted_run_resumes_without_retranslating_accepted_segment(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = ASOSTStore(Path(temp.name) / "state.db")
        calls = []
        _FailSecondTranslator.translations = 0
        failing = BookSupervisor(
            store,
            lambda role, **_identity: _FailSecondTranslator(role, calls),
        )
        book, run = failing.start("book.pdf", b"resume", "owner")
        chapters = [
            {"id": "chapter_1", "content": "first source " * 20},
            {"id": "chapter_2", "content": "second source " * 20},
        ]
        with self.assertRaises(ConnectionError):
            failing.process_chapters(book, run, chapters)
        persisted = store.get_run(run.run_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted["state"], RunState.RETRYABLE_FAILURE.value)

        resumed_calls = []
        resumed = BookSupervisor(
            store, lambda role, **_identity: _FakeAgent(role, resumed_calls)
        )
        result = resumed.process_chapters(book, run, chapters)
        self.assertEqual(result["state"], RunState.COMPLETED.value)
        self.assertEqual(
            [role for role, _ in resumed_calls].count("translator"), 1,
            "the previously accepted first chapter must be loaded from checkpoint",
        )

    def test_segmentation_preserves_every_character(self):
        source = ("paragraph one " * 80) + "\n\n" + ("paragraph two " * 80)
        chunks = split_text(source, 300)
        self.assertEqual("".join(chunks), source)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))

    def test_deterministic_quality_checks_full_translation(self):
        self.assertTrue(deterministic_quality("source " * 100, "قصير"))
        self.assertTrue(deterministic_quality("source", "English words remain here"))

    def test_images_are_placed_by_source_page_ratio(self):
        chapter = {"start_page": 10, "end_page": 12}
        translated = "أول\n\nثان\n\nثالث"
        placed = place_chapter_images(chapter, translated, [
            {"page": 11, "name": "illustration.png", "class": "full_page"}
        ])
        self.assertIn("[IMG:illustration.png|full_page]", placed)
        self.assertEqual(len(placed.split("\n\n")), 4)


class GeminiContractTests(unittest.TestCase):
    def test_registry_handler_is_truly_async(self):
        self.assertTrue(inspect.iscoroutinefunction(asost_gemini_tools._gemini_handler))

    def test_structured_outputs_are_validated(self):
        critique = asost_gemini_tools._validate_output(
            "critique", '{"score": 92, "issues": []}'
        )
        self.assertEqual(critique["score"], 92)
        with self.assertRaises(ValueError):
            asost_gemini_tools._validate_output("critique", '{"score": 101}')
        with self.assertRaises(ValueError):
            asost_gemini_tools._validate_output("terminology", '{"terms": {}}')
        prompt = asost_gemini_tools._build_prompt(
            "critique", "English source", "context", "glossary", "مسودة عربية"
        )
        self.assertIn("SOURCE TEXT:\nEnglish source", prompt)
        self.assertIn("ARABIC DRAFT:\nمسودة عربية", prompt)

    def test_failure_policy_does_not_rotate_for_local_errors(self):
        self.assertEqual(asost_gemini_tools._failure_policy({}), (False, "local_error"))
        self.assertEqual(
            asost_gemini_tools._failure_policy({"status": 429, "reason": "rate_limit"}),
            (True, "rate_limit"),
        )


class AgentPoolTests(unittest.TestCase):
    def test_agent_uses_hermes_openrouter_pool_and_isolated_session(self):
        captured = {}

        class Credential:
            runtime_api_key = "secret-test-key"

        class Pool:
            def select(self):
                return Credential()

        class FakeAgent:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        run_agent = types.ModuleType("run_agent")
        setattr(run_agent, "AIAgent", FakeAgent)
        credential_pool = types.ModuleType("agent.credential_pool")
        setattr(credential_pool, "load_pool", lambda provider: Pool())
        with patch.dict(sys.modules, {
            "run_agent": run_agent,
            "agent.credential_pool": credential_pool,
        }):
            from asost.agent_runner import build_agent

            agent = build_agent(
                "translator", book_id="book_abc", run_id="run_xyz"
            )
        self.assertEqual(captured["api_key"], "secret-test-key")
        self.assertEqual(captured["session_id"], "asost:book_abc:run_xyz:translator")
        self.assertIsNotNone(captured["credential_pool"])
        self.assertTrue(captured["checkpoints_enabled"])
        self.assertEqual(agent.asost_identity["role"], "translator")


class MemoryToolTests(unittest.TestCase):
    def test_scoped_memory_uses_transactional_store(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            "os.environ", {"ASOST_STATE_DB": str(Path(root) / "state.db")}
        ):
            store = ASOSTStore(Path(root) / "state.db")
            book = BookIdentity.from_bytes("book.pdf", b"memory-book")
            run = RunIdentity(book.book_id)
            store.create_run(book, run, "owner")
            result = asost_tools.asost_memory_set(
                "hero", '"ساتو"', book.book_id, "terminology"
            )
            self.assertIn(book.book_id, result)
            self.assertEqual(
                asost_tools.asost_memory_get(
                    "hero", book.book_id, "terminology"
                ),
                "ساتو",
            )


if __name__ == "__main__":
    unittest.main()
