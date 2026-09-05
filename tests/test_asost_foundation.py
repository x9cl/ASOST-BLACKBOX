"""Offline unit tests for the first Hermes/ASOST integration foundation."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asost.config import ASOSTSettings
from asost.orchestrator import ASOSTOrchestrator


class SettingsTests(unittest.TestCase):
    def test_paths_default_to_this_checkout(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = ASOSTSettings.load()
        self.assertEqual(
            resolved.project_root,
            Path(__file__).resolve().parent.parent,
        )
        self.assertEqual(resolved.memory_path, resolved.project_root / "asost_memory.json")
        self.assertEqual(resolved.asost_main, resolved.project_root / "assost-main")

    def test_runtime_paths_and_limits_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {
                "ASOST_PROJECT_ROOT": root,
                "ASOST_MEMORY_PATH": f"{root}/state/memory.json",
                "ASOST_GEMINI_MAX_INPUT_CHARS": "1234",
                "ASOST_GEMINI_POOL_FAILOVERS": "7",
            },
            clear=True,
        ):
            resolved = ASOSTSettings.load()
        self.assertEqual(resolved.project_root, Path(root).resolve())
        self.assertEqual(resolved.gemini_max_input_chars, 1234)
        self.assertEqual(resolved.gemini_pool_failovers, 7)


class _FakeOrchestrator(ASOSTOrchestrator):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.saved = {}

    def _chat(self, name, message):
        self.calls.append((name, message))
        return next(self.responses)

    def save_state(self, key, value):
        self.saved[key] = value
        return True

    def load_state(self, key, default=None):
        return default


class OrchestratorTests(unittest.TestCase):
    def test_light_acceptance_does_not_call_deep_critic(self):
        orchestrator = _FakeOrchestrator([
            "ترجمة عربية أدبية كاملة",
            '{"score": 91, "notes": []}',
        ])
        result = orchestrator.translate_page(
            3,
            "A sufficiently long source passage for the translation workflow "
            "to accept and evaluate without triggering the short-input guard.",
            "The previous scene ended at the city gate.",
        )
        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["revision_rounds"], 0)
        self.assertEqual([name for name, _ in orchestrator.calls], [
            "translator", "critic_light",
        ])
        self.assertIn("previous scene", orchestrator.calls[0][1])
        self.assertIn("page_3_result", orchestrator.saved)


if __name__ == "__main__":
    unittest.main()
