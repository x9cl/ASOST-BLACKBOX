"""Regression tests for the full-page deterministic translation gate."""
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "asost"))

from orchestrator import ASOSTOrchestrator, SEGMENT_CHAR_LIMIT, _segment_source  # noqa: E402


def test_missing_tail_of_long_page_is_rejected_before_critics():
    paragraph = (
        "The travelers crossed the silent valley while the guide carefully "
        "described every landmark and warned them not to leave the road. " * 3
    ).strip()
    source = "\n\n".join(paragraph for _ in range(12))
    assert len(source) > 3000

    orchestrator = ASOSTOrchestrator.__new__(ASOSTOrchestrator)
    orchestrator._agents = {}
    translator_calls = 0

    def fake_chat(agent, prompt):
        nonlocal translator_calls
        if agent != "translator":
            raise AssertionError("a deterministic failure must not reach a critic")
        translator_calls += 1
        segment = prompt.split("\n\n", 1)[-1]
        if translator_calls == len(_segment_source(source)):
            return ""  # realistic truncation: good opening, missing final unit
        return "\n\n".join(
            "عبر المسافرون الوادي الصامت بينما وصف الدليل كل معلم بعناية "
            "وحذرهم من مغادرة الطريق. " * 4
            for _ in segment.split("\n\n")
        )

    orchestrator._chat = fake_chat
    orchestrator.save_state = lambda *args, **kwargs: True

    result = orchestrator.translate_page(41, source)

    assert translator_calls > 1
    assert result["decision"] == "rejected"
    assert result["validation"]["passed"] is False
    assert result["validation"]["checks"]["paragraph_coverage"] is False


def test_segmentation_never_exceeds_review_budget():
    source = "\n\n".join(("Dialogue line. " * 200) for _ in range(3))
    segments = _segment_source(source)
    assert len(segments) > 1
    assert all(len(segment) <= SEGMENT_CHAR_LIMIT for segment in segments)
