from threading import Event
import pytest
from asost.gemini_tool import GeminiTool
from asost.providers import CancelledError, FakeProvider, ProviderError


def test_success_is_offline_and_uses_symbolic_credential(fake_pool):
    provider = FakeProvider(["ترجمة ناجحة"])
    assert GeminiTool(provider, fake_pool).translate("hello") == "ترجمة ناجحة"
    assert provider.calls[0]["credential"] == "credential-1"


def test_failure_rotates_credentials_and_redacts_errors(fake_pool, caplog):
    secrets = ("credential-secret-A", "credential-secret-B")
    provider = FakeProvider([RuntimeError(f"SDK leaked {secrets[0]}"), RuntimeError(secrets[1])])
    with pytest.raises(ProviderError) as caught:
        GeminiTool(provider, fake_pool, max_attempts=2).translate("hello")
    assert [call["credential"] for call in provider.calls] == ["credential-1", "credential-2"]
    surfaces = str(caught.value) + caplog.text + repr(fake_pool) + repr(provider.calls)
    assert all(secret not in surfaces for secret in secrets)


def test_pre_cancelled_request_never_calls_provider(fake_pool):
    event = Event(); event.set()
    provider = FakeProvider(["unused"])
    with pytest.raises(CancelledError):
        GeminiTool(provider, fake_pool).translate("hello", cancel_event=event)
    assert provider.calls == []
