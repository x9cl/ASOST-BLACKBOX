import json
import pytest
from asost.gemini_tool import GeminiTool
from asost.hermes_dispatch import ASOSTHermesDispatcher
from asost.providers import FakeCredentialPool, FakeProvider
from asost.workflow import BookWorkflow


def test_hermes_dispatches_full_offline_book(synthetic_book, memory):
    provider = FakeProvider(["الصفحة الأولى", "الصفحة الثانية"])
    workflow = BookWorkflow(GeminiTool(provider, FakeCredentialPool(["dispatch-secret"])), memory)
    result = ASOSTHermesDispatcher(workflow).dispatch("translate_book", manifest=synthetic_book)
    assert result["status"] == "completed"
    assert list(result["pages"]) == ["1", "2"]
    assert result["provenance"][0]["assets"] == ["garden.svg"]
    image = synthetic_book.parent / result["provenance"][0]["assets"][0]
    assert image.is_file() and image.read_text(encoding="utf-8").startswith("<svg")
    serialized = json.dumps(result, ensure_ascii=False)
    assert "dispatch-secret" not in serialized


def test_unknown_command_is_rejected(synthetic_book, memory):
    workflow = BookWorkflow(GeminiTool(FakeProvider(), FakeCredentialPool(["x"])), memory)
    with pytest.raises(ValueError, match="unsupported"):
        ASOSTHermesDispatcher(workflow).dispatch("delete_everything", manifest=synthetic_book)
