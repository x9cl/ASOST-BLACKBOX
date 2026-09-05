"""Unit tests for bounded translation execution and trace provenance."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "asost"))

from execution import (  # noqa: E402
    ExecutionTrace,
    InvalidExecutionTrace,
    Supervisor,
    ToolCallBudgetExceeded,
    TranslationPlanner,
)


class ExecutionGovernanceTest(unittest.TestCase):
    def test_planner_returns_single_bounded_route(self):
        plan = TranslationPlanner.plan("A source chunk")
        self.assertEqual(plan.route, "agent")
        self.assertEqual(plan.max_tool_calls, 0)

    def test_supervisor_rejects_calls_over_budget(self):
        plan = TranslationPlanner.plan(
            "A source chunk", requires_translation_tool=True)
        supervisor = Supervisor(plan)
        supervisor.record_tool_call("asost_translate_text")
        with self.assertRaises(ToolCallBudgetExceeded):
            supervisor.record_tool_call("asost_translate_text")

    def test_supervisor_blocks_forbidden_provider_fallback(self):
        plan = TranslationPlanner.plan("Sensitive source", sensitive=True)
        with self.assertRaisesRegex(PermissionError, "fallback is forbidden"):
            Supervisor(plan).require_fallback_allowed()

    def test_rejects_unjustified_duplicate_full_translation(self):
        trace = ExecutionTrace("same-source-hash")
        trace.add("full_translation", "translator", model="agent")
        trace.add("critic", "critic_light")
        trace.add("full_translation", "translator", model="gemini")
        with self.assertRaisesRegex(InvalidExecutionTrace, "require justification"):
            trace.validate()

    def test_allows_justified_duplicate_full_translation(self):
        trace = ExecutionTrace("same-source-hash")
        trace.add("full_translation", "translator", model="agent")
        trace.add("full_translation", "translator", model="gemini",
                  justification="critic requested independent adjudication")
        self.assertTrue(trace.validate())


if __name__ == "__main__":
    unittest.main()
