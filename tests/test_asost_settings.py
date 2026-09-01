"""Unit tests for shared ASOST configuration (no live API calls)."""

import unittest

from asost.settings import ASOSTSettings, TASKS
from hermes.tools.asost_gemini_tools import settings_for_run


class ASOSTSettingsTests(unittest.TestCase):
    def test_model_per_task_and_numeric_settings(self):
        env = {
            "ASOST_GEMINI_MODEL": "default-model",
            "ASOST_GEMINI_MODEL_TRANSLATOR": "translation-model",
            "ASOST_GEMINI_TIMEOUT_SECONDS": "12.5",
            "ASOST_GEMINI_MAX_OUTPUT_TOKENS": "2048",
            "ASOST_GEMINI_TEMPERATURE": "0.7",
            "ASOST_GEMINI_MAX_FAILOVERS": "0",
            "ASOST_GEMINI_RUN_REQUEST_BUDGET": "9",
            "ASOST_GEMINI_BOOK_TOKEN_BUDGET": "50000",
        }
        settings = ASOSTSettings.from_env(env)
        self.assertEqual(settings.model_for("translator"), "translation-model")
        self.assertEqual(settings.model_for("critic_light"), "default-model")
        self.assertEqual(settings.max_failovers, 0)
        self.assertEqual(settings.timeout_seconds, 12.5)
        self.assertEqual(settings.temperature, 0.7)

    def test_each_task_can_select_a_model(self):
        env = {f"ASOST_GEMINI_MODEL_{task.upper()}": task for task in TASKS}
        settings = ASOSTSettings.from_env(env)
        self.assertEqual(dict(settings.models), {task: task for task in TASKS})

    def test_non_numeric_values_are_rejected(self):
        for name in (
            "ASOST_GEMINI_TIMEOUT_SECONDS", "ASOST_GEMINI_MAX_OUTPUT_TOKENS",
            "ASOST_GEMINI_TEMPERATURE", "ASOST_GEMINI_MAX_FAILOVERS",
            "ASOST_GEMINI_RUN_REQUEST_BUDGET", "ASOST_GEMINI_BOOK_TOKEN_BUDGET",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                ASOSTSettings.from_env({name: "not-a-number"})

    def test_zero_and_negative_limits_are_rejected(self):
        positive = (
            "ASOST_GEMINI_TIMEOUT_SECONDS", "ASOST_GEMINI_MAX_OUTPUT_TOKENS",
            "ASOST_GEMINI_RUN_REQUEST_BUDGET", "ASOST_GEMINI_BOOK_TOKEN_BUDGET",
        )
        for name in positive:
            for value in ("0", "-1"):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    ASOSTSettings.from_env({name: value})
        with self.assertRaisesRegex(ValueError, "ASOST_GEMINI_MAX_FAILOVERS"):
            ASOSTSettings.from_env({"ASOST_GEMINI_MAX_FAILOVERS": "-1"})
        with self.assertRaisesRegex(ValueError, "ASOST_GEMINI_TEMPERATURE"):
            ASOSTSettings.from_env({"ASOST_GEMINI_TEMPERATURE": "-0.1"})

    def test_adapter_reloads_between_runs(self):
        first = settings_for_run({"ASOST_GEMINI_MAX_OUTPUT_TOKENS": "100"})
        second = settings_for_run({"ASOST_GEMINI_MAX_OUTPUT_TOKENS": "200"})
        self.assertEqual(first.max_output_tokens, 100)
        self.assertEqual(second.max_output_tokens, 200)


if __name__ == "__main__":
    unittest.main()
