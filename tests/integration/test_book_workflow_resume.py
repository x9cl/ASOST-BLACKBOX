from threading import Event
import pytest
from asost.gemini_tool import GeminiTool
from asost.providers import CancelledError, FakeCredentialPool, FakeProvider, ProviderError
from asost.workflow import BookWorkflow


class CancelAfterFirst(FakeProvider):
    def __init__(self, event):
        super().__init__(["الأولى", "never"]); self.event = event
    def generate(self, *args, **kwargs):
        value = super().generate(*args, **kwargs)
        self.event.set()
        return value


def test_cancel_checkpoint_then_resume_without_repeating_page(synthetic_book, memory):
    event = Event()
    first = CancelAfterFirst(event)
    workflow = BookWorkflow(GeminiTool(first, FakeCredentialPool(["resume-secret"])), memory)
    with pytest.raises(CancelledError):
        workflow.run(synthetic_book, event)
    checkpoint = memory.read("book")
    assert checkpoint["status"] == "cancelled"
    assert list(checkpoint["pages"]) == ["1"]

    second = FakeProvider(["الثانية"])
    result = BookWorkflow(GeminiTool(second, FakeCredentialPool(["new-secret"])), memory).run(synthetic_book)
    assert result["status"] == "completed"
    assert result["pages"]["1"]["translation"] == "الأولى"
    assert result["pages"]["2"]["translation"] == "الثانية"
    assert len(second.calls) == 1


def test_failure_is_checkpointed_and_resumable(synthetic_book, memory):
    failing = FakeProvider([RuntimeError("credential failure")])
    workflow = BookWorkflow(GeminiTool(failing, FakeCredentialPool(["failure-secret"]), max_attempts=1), memory)
    with pytest.raises(ProviderError):
        workflow.run(synthetic_book)
    assert memory.read("book")["status"] == "failed"
