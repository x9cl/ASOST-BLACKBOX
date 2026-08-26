from asost.workflows.book_supervisor import BookSupervisor
from asost.workflows.states import BookState, BookStateMachine, InvalidStateTransition


class Extractor:
    def __init__(self, calls): self.calls = calls
    def extract(self, path):
        self.calls.append("extract")
        return {"title": "Book", "total_pages": 1,
                "chapters": [{"id": "c1", "title": "One", "content": "source"}]}


def build(calls, light_score=90):
    def tool(name, result=None):
        def invoke(*args, **kwargs):
            calls.append(name)
            return result
        return invoke
    return BookSupervisor(
        extractor=Extractor(calls), book_adapter=tool("book_adapter", {}),
        context_keeper=tool("context_keeper", {}), terminology=tool("terminology", {}),
        translator=tool("translator", "translated"),
        light_critic=tool("light", {"score": light_score}),
        deep_critic=tool("deep", {"score": 90}), reviser=tool("reviser", None),
        quality_gate=tool("quality", {"accepted": True}), memory_commit=tool("memory"),
        reconstruct=tool("reconstruct", "out.docx"), verify=tool("verify", {"valid": True}),
    )


def test_happy_path_order_and_conditional_deep_review():
    calls = []
    run = build(calls).start("book.pdf")
    assert run.state is BookState.COMPLETED
    assert calls == ["extract", "book_adapter", "context_keeper", "terminology", "translator",
                     "light", "reviser", "quality", "memory", "reconstruct", "verify"]
    assert [x["state"] for x in run.history] == [s.value for s in list(BookState)[1:9]]


def test_deep_critic_runs_only_below_threshold():
    calls = []
    build(calls, light_score=70).start("book.pdf")
    assert calls.index("deep") == calls.index("light") + 1
    assert calls.index("reviser") == calls.index("deep") + 1


def test_state_machine_rejects_skips():
    machine = BookStateMachine()
    try:
        machine.transition(BookState.TRANSLATING)
    except InvalidStateTransition:
        pass
    else:
        raise AssertionError("transition skip accepted")
