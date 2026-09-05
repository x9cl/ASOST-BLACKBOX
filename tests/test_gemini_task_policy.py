"""Contract tests for task-specific Gemini provider policies."""

import asyncio
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "assost-main"))

from asost_config import GeminiTaskPolicy, load_gemini_task_policies  # noqa: E402


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return {
            "modelVersion": "resolved-" + ("critic" if len(self.owner.calls) == 2 else "translation"),
            "candidates": [{
                "content": {"parts": [{"text": "ok"}]},
                "finishReason": "STOP",
            }]
        }


class FakeSession:
    closed = False

    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = FakeResponse()
        response.owner = self
        return response


def test_translation_and_critique_use_distinct_policies_with_one_credential_pool(
    monkeypatch, tmp_path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASOST_GEMINI_KEYS", "shared-credential")
    PF = importlib.import_module("PF")
    policies = {
        "translation": GeminiTaskPolicy(
            "gemini-translation", 0.35, 8000, 91, "translation",
            ("gemini-translation-fallback",),
        ),
        "critique": GeminiTaskPolicy(
            "gemini-critic", 0.0, 1200, 17, "critique",
        ),
    }
    provider = PF.EnhancedGeminiAPI(task_policies=policies)
    provider.session = FakeSession()

    asyncio.run(provider.make_precision_request("translate", request_type="translation"))
    asyncio.run(provider.make_precision_request("review", request_type="critique"))

    assert provider.api_keys == ["shared-credential"]
    translation_call, critique_call = provider.session.calls
    assert "/gemini-translation:generateContent" in translation_call[0]
    assert translation_call[1]["json"]["generationConfig"] == {
        "temperature": 0.35,
        "topK": 20,
        "topP": 0.9,
        "maxOutputTokens": 8000,
        "candidateCount": 1,
        "stopSequences": ["###TRANSLATION_END###", "###END###"],
    }
    assert translation_call[1]["timeout"].total == 91
    assert "/gemini-critic:generateContent" in critique_call[0]
    assert critique_call[1]["json"]["generationConfig"]["temperature"] == 0.0
    assert critique_call[1]["json"]["generationConfig"]["maxOutputTokens"] == 1200
    assert critique_call[1]["timeout"].total == 17
    assert [entry["model"] for entry in provider.request_provenance] == [
        "resolved-translation", "resolved-critic",
    ]
    assert [entry["requested_model"] for entry in provider.request_provenance] == [
        "gemini-translation", "gemini-critic",
    ]


def test_fallback_models_are_loaded_from_environment():
    policies = load_gemini_task_policies({
        "ASOST_GEMINI_POLICIES": (
            '{"translation":{"model":"primary",'
            '"fallback_models":["backup-a","backup-b"]}}'
        )
    })
    assert policies["translation"].models == ("primary", "backup-a", "backup-b")
