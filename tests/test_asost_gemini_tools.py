import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "hermes"))

from tools import asost_gemini_tools as tools


def test_critique_uses_separate_inputs_and_validates_result():
    calls = []

    def caller(prompt):
        calls.append(prompt)
        return json.dumps({
            "version": "1.0", "score": 91, "issues": ["word choice"],
            "severity": "low", "source_span": "source", "draft_span": "draft",
            "confidence": 0.8,
        })

    result = json.loads(tools.handle_critique({
        "source_text": "source", "draft_text": "draft",
        "translation_directive": "formal", "glossary": {"book": "كتاب"},
    }, caller=caller))
    assert result["score"] == 91
    assert all(value in calls[0] for value in ("source", "draft", "formal", "كتاب"))


def test_invalid_score_gets_one_repair_then_typed_error():
    calls = []

    def caller(prompt):
        calls.append(prompt)
        return json.dumps({
            "version": "1.0", "score": 101, "issues": [], "severity": "none",
            "source_span": "", "draft_span": "", "confidence": 1,
        })

    result = json.loads(tools.handle_critique({
        "source_text": "source", "draft_text": "draft",
        "translation_directive": "", "glossary": {},
    }, caller=caller))
    assert len(calls) == 2
    assert result["error"]["type"] == "GeminiOutputValidationError"
    assert result["error"]["repair_attempted"] is True


def test_translation_repairs_invalid_json_once():
    replies = iter(("not json", '{"version":"1.0","translation":"ترجمة"}'))
    result = json.loads(tools.handle_translation(
        {"source_text": "text"}, caller=lambda _: next(replies)
    ))
    assert result == {"version": "1.0", "translation": "ترجمة"}


@pytest.mark.parametrize("score", [-1, 100.1, True])
def test_score_type_and_bounds_are_strict(score):
    payload = {
        "version": "1.0", "score": score, "issues": [], "severity": "none",
        "source_span": "", "draft_span": "", "confidence": 1,
    }
    with pytest.raises(tools.SchemaValidationError):
        tools._parse_critique(payload)
