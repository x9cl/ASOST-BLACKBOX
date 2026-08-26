import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "asost"))

from book_workflow import BookWorkflow  # noqa: E402


STYLE = {"register": "msa", "narration": "lyrical", "dialogue": "plain", "terminology": "fixed"}
DIRECTIVE = {
    "genre": "fantasy", "tone": "warm", "characters": [], "places": [],
    "events": [], "relationships": [], "style_policy": STYLE,
}


class FakeAgents:
    def __init__(self):
        self.calls = []
        self.context_version = 0

    def chat(self, agent, message):
        payload = json.loads(message)
        self.calls.append((agent, payload))
        if agent == "book_adapter":
            return json.dumps(DIRECTIVE)
        if agent == "translator":
            return f"ترجمة {payload['chapter']['id']}"
        if payload["task"] == "prepare_chapter_context":
            context = payload["payload"]["book_context"]
            return json.dumps({
                "chapter_id": payload["payload"]["chapter"]["id"],
                **context,
                "continuity_notes": [f"version:{self.context_version}"],
            })
        self.context_version += 1
        updated = dict(payload["payload"]["previous_book_context"])
        updated["events"] = [{"chapter_id": payload["payload"]["chapter"]["id"], "summary": f"version:{self.context_version}"}]
        return json.dumps(updated)


def test_directive_reaches_translator_and_adapter_precedes_segmentation():
    fake = FakeAgents()
    segmented_after = []

    def segmenter(_book):
        segmented_after.append([name for name, _ in fake.calls])
        return [{"id": "one", "content": "First"}]

    BookWorkflow(fake.chat).run({"text": "whole book"}, segmenter)

    translator_call = next(payload for name, payload in fake.calls if name == "translator")
    assert translator_call["translation_directive"] == DIRECTIVE
    assert segmented_after == [["book_adapter"]]
    assert sum(name == "book_adapter" for name, _ in fake.calls) == 1


def test_accepted_previous_chapter_context_reaches_next_chapter():
    fake = FakeAgents()
    BookWorkflow(fake.chat).run(
        {"text": "whole book"},
        lambda _: [{"id": "one"}, {"id": "two"}],
    )

    preparations = [payload for name, payload in fake.calls
                    if name == "context_keeper" and payload["task"] == "prepare_chapter_context"]
    assert preparations[1]["payload"]["book_context"]["events"] == [
        {"chapter_id": "one", "summary": "version:1"}
    ]


def test_agent_cannot_add_undefined_json_keys():
    fake = FakeAgents()
    fake.chat = lambda _agent, _message: json.dumps({**DIRECTIVE, "free_form": "forbidden"})
    with pytest.raises(ValueError, match="undefined keys"):
        BookWorkflow(fake.chat).run({"text": "book"}, lambda _: [])
