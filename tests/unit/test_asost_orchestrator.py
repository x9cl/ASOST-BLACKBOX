import pytest
import asost.orchestrator as module


class ScriptedOrchestrator(module.ASOSTOrchestrator):
    def __init__(self, replies):
        self.replies = iter(replies); self.saved = {}; self.names = []
    def _chat(self, name, message):
        self.names.append(name); return next(self.replies)
    def save_state(self, key, value):
        self.saved[key] = value
    def load_state(self, key, default=None):
        return default


def test_light_acceptance_is_terminal():
    orch = ScriptedOrchestrator(["نص عربي", '{"score": 91}'])
    result = orch.translate_page(1, "source text " * 6)
    assert result["decision"] == "accepted"
    assert orch.names == ["translator", "critic_light"]


def test_deep_revise_light_accept_transitions():
    replies = ["draft", '{"score": 60}', '{"score": 50, "notes":["fix"]}', "revised", '{"score": 90}']
    result = ScriptedOrchestrator(replies).translate_page(2, "source text " * 6)
    assert result["decision"] == "accepted"
    assert result["revision_rounds"] == 1
    assert result["translation"] == "revised"


def test_all_failures_finish_with_best_effort(monkeypatch):
    monkeypatch.setattr(module, "MAX_REVISION_ROUNDS", 1)
    replies = ["draft", '{"score": 70}', '{"score": 75}', "revision", '{"score": 65}', '{"score": 60}']
    result = ScriptedOrchestrator(replies).translate_page(3, "source text " * 6)
    assert result["decision"] == "best_effort"
    assert result["best_score"] == 75
    assert result["translation"] == "draft"


def test_invalid_source_fails_before_provider():
    orch = ScriptedOrchestrator([])
    with pytest.raises(ValueError):
        orch.translate_page(1, "short")
    assert orch.names == []
