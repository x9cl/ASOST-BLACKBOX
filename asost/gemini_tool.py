"""Gemini-shaped translation tool with injected provider and credential pool."""
from __future__ import annotations
from .providers import CancelledError, ProviderError


class GeminiTool:
    def __init__(self, provider, credential_pool, *, max_attempts=3):
        self.provider = provider
        self.pool = credential_pool
        self.max_attempts = max_attempts

    def translate(self, text, context="", cancel_event=None):
        if not text.strip():
            raise ValueError("text cannot be empty")
        last = None
        for _ in range(self.max_attempts):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("operation cancelled")
            credential = self.pool.acquire()
            try:
                return self.provider.generate(
                    f"Context: {context}\nTranslate to Arabic:\n{text}",
                    credential=credential, cancel_event=cancel_event)
            except CancelledError:
                raise
            except ProviderError as exc:
                last = exc
        raise ProviderError(f"translation failed after {self.max_attempts} attempts") from None
