"""Configuration primitives for the offline-testable ASOST pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, repr=False)
class ASOSTConfig:
    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    credentials: tuple[str, ...] = field(default_factory=tuple)
    max_attempts: int = 3

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        attempts = int(env.get("ASOST_MAX_ATTEMPTS", "3"))
        if attempts < 1:
            raise ValueError("ASOST_MAX_ATTEMPTS must be positive")
        return cls(
            provider=env.get("ASOST_PROVIDER", "gemini"),
            model=env.get("ASOST_MODEL", "gemini-2.5-flash"),
            credentials=_split(env.get("ASOST_CREDENTIALS", "")),
            max_attempts=attempts,
        )

    def __repr__(self):
        return (f"ASOSTConfig(provider={self.provider!r}, model={self.model!r}, "
                f"credentials=<redacted:{len(self.credentials)}>, max_attempts={self.max_attempts})")
