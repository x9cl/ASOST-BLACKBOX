"""Regression tests for the ASOST async registry boundary."""

import asyncio
import sys
from pathlib import Path

import pytest


HERMES = Path(__file__).resolve().parents[1] / "hermes"
if str(HERMES) not in sys.path:
    sys.path.insert(0, str(HERMES))

from tools import asost_tools


class _Entry:
    id = "credential-1"
    runtime_api_key = "test-key"


class _Pool:
    def __init__(self):
        self.released = []

    def acquire_lease(self):
        return _Entry.id

    def entries(self):
        return [_Entry()]

    def release_lease(self, credential_id):
        self.released.append(credential_id)


def _install_fakes(monkeypatch, api_type):
    pool = _Pool()
    monkeypatch.setattr(asost_tools, "_get_pool", lambda: pool)

    class Translator:
        def __init__(self, api):
            self.api = api

        async def translate_with_completion_guarantee(self, text, context):
            return await self.api.translate_text(text, context), 0.0, "test-key"

    def make_engine(keys):
        api = api_type(keys)
        return api, Translator(api)

    monkeypatch.setattr(asost_tools, "_get_engine", make_engine)
    return pool


def test_registry_dispatches_asost_from_sync_context(monkeypatch):
    instances = []

    class API:
        def __init__(self, keys):
            self.keys = keys
            self.closed = False
            instances.append(self)

        async def translate_text(self, text, context):
            return f"{text}:{context}"

        async def cleanup(self):
            self.closed = True

    pool = _install_fakes(monkeypatch, API)

    result = asost_tools.registry.dispatch(
        "asost_translate_text", {"text": "hello", "context": "novel"}
    )

    assert result == "hello:novel"
    assert instances[0].keys == ["test-key"]
    assert instances[0].closed is True
    assert pool.released == [_Entry.id]


def test_dispatch_with_running_loop_and_cancellation_release_resources(monkeypatch):
    instances = []
    started = asyncio.Event()

    class API:
        def __init__(self, keys):
            self.closed = False
            instances.append(self)

        async def translate_text(self, text, context):
            if text == "wait":
                started.set()
                await asyncio.Event().wait()
            return text

        async def cleanup(self):
            self.closed = True

    pool = _install_fakes(monkeypatch, API)

    async def exercise():
        # Registry dispatch is synchronous but must remain valid when its caller
        # already owns an event loop; Hermes bridges it onto a worker loop.
        assert asost_tools.registry.dispatch(
            "asost_translate_text", {"text": "running-loop"}
        ) == "running-loop"

        task = asyncio.create_task(
            asost_tools.asost_translate_text("wait")
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    assert all(instance.closed for instance in instances)
    assert pool.released == [_Entry.id, _Entry.id]
