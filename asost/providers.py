"""Provider contracts and deterministic, network-free test doubles."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Iterable


class ProviderError(RuntimeError):
    """A provider failure safe to expose to callers."""


class CancelledError(ProviderError):
    pass


@dataclass(frozen=True)
class Credential:
    name: str
    value: str

    def __repr__(self):
        return f"Credential(name={self.name!r}, value=<redacted>)"


class FakeCredentialPool:
    """Thread-safe round-robin pool; values never occur in its representation."""
    def __init__(self, credentials: Iterable[str]):
        values = tuple(credentials)
        if not values:
            raise ValueError("credential pool cannot be empty")
        self._items = tuple(Credential(f"credential-{i + 1}", value) for i, value in enumerate(values))
        self._cursor = 0
        self._lock = Lock()

    def acquire(self) -> Credential:
        with self._lock:
            item = self._items[self._cursor]
            self._cursor = (self._cursor + 1) % len(self._items)
            return item

    def __repr__(self):
        return f"FakeCredentialPool(size={len(self._items)}, cursor={self._cursor})"


class FakeProvider:
    """Scripted provider. Each call consumes a response or an exception."""
    network_enabled = False

    def __init__(self, responses=(), name="fake"):
        self.name = name
        self._responses = list(responses)
        self.calls = []

    def generate(self, prompt: str, *, credential: Credential, cancel_event=None) -> str:
        self.calls.append({"prompt": prompt, "credential": credential.name})
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("operation cancelled")
        if not self._responses:
            return f"ترجمة مصطنعة: {prompt}"
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            # Deliberately do not chain arbitrary SDK errors: they can contain keys.
            raise ProviderError(f"{self.name} request failed") from None
        return str(response)
