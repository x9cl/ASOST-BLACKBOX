"""Offline coverage for ASOST's use of Hermes credential ownership."""

import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hermes"))
sys.path.insert(0, str(ROOT))

from agent.credential_pool import CredentialPool, PooledCredential  # noqa: E402
from asost import agent_runner  # noqa: E402


def _entry(entry_id, key, priority):
    return PooledCredential(
        provider="openrouter",
        id=entry_id,
        label=f"credential-{entry_id}",
        auth_type="api_key",
        priority=priority,
        source="manual",
        access_token=key,
    )


def _pool(monkeypatch, count=2):
    entries = [_entry(str(i), f"offline-secret-{i}", i) for i in range(count)]
    pool = CredentialPool("openrouter", entries)
    # Pool persistence is irrelevant to policy and must remain offline.
    monkeypatch.setattr(pool, "_persist", lambda *args, **kwargs: None)
    return pool


def test_available_credential_is_selected(monkeypatch):
    pool = _pool(monkeypatch)
    assert pool.select().id == "0"


def test_lease_is_acquired_and_released(monkeypatch):
    pool = _pool(monkeypatch)
    leased = pool.acquire_lease()
    assert leased == "0"
    assert pool._active_leases == {"0": 1}
    pool.release_lease(leased)
    assert pool._active_leases == {}


@pytest.mark.parametrize("status_code", [429, 401])
def test_failure_rotates_away_from_failed_credential(monkeypatch, status_code):
    pool = _pool(monkeypatch)
    failed = pool.select()
    replacement = pool.mark_exhausted_and_rotate(
        status_code=status_code,
        credential_id=failed.id,
        api_key_hint=failed.access_token,
    )
    assert replacement is not None
    assert replacement.id != failed.id
    assert replacement.access_token != failed.access_token


def test_secrets_do_not_appear_in_pool_logs_or_results(monkeypatch, caplog):
    pool = _pool(monkeypatch)
    secret = pool.select().access_token
    with caplog.at_level(logging.DEBUG):
        replacement = pool.mark_exhausted_and_rotate(
            status_code=429,
            api_key_hint=secret,
        )
    assert secret not in caplog.text
    # Hermes returns a credential object internally, never a secret-bearing
    # response payload for the caller/agent transcript.
    public_result = {"credential_id": replacement.id}
    assert secret not in repr(public_result)


@pytest.mark.parametrize("credential_count", [1, 3])
def test_build_agent_keeps_identity_independent_of_pool_size(
    monkeypatch, tmp_path, credential_count
):
    pool = _pool(monkeypatch, credential_count)
    calls = []

    runtime_module = ModuleType("hermes_cli.runtime_provider")

    def resolve_runtime_provider(**kwargs):
        calls.append(kwargs)
        selected = pool.select()
        return {
            "provider": "openrouter",
            "requested_provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": selected.access_token,
            "credential_pool": pool,
        }

    runtime_module.resolve_runtime_provider = resolve_runtime_provider
    monkeypatch.setitem(sys.modules, "hermes_cli.runtime_provider", runtime_module)

    run_agent_module = ModuleType("run_agent")

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    run_agent_module.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, "run_agent", run_agent_module)
    monkeypatch.setattr(agent_runner, "HERMES_HOME", str(tmp_path / "hermes-home"))

    agent = agent_runner.build_agent("translator")

    assert calls == [{"requested": "openrouter", "target_model": "stealth/ox-alpha"}]
    assert agent.kwargs["provider"] == "openrouter"
    assert agent.kwargs["model"] == "stealth/ox-alpha"
    assert agent.kwargs["credential_pool"] is pool
    assert agent.asost_identity["role"] == "translator"
