"""Environment-backed configuration shared by ASOST integrations.

Configuration is deliberately read by :meth:`ASOSTSettings.from_env`, rather
than at module import time.  A caller should create one settings snapshot at
the start of a run.  A later run can therefore pick up changed environment
variables without restarting Hermes; an in-flight run keeps a consistent
snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Mapping


TASKS = ("translator", "critic_light", "critic_deep", "reviser", "book_adapter")
DEFAULT_MODEL = "gemini-2.5-flash"


def _number(env: Mapping[str, str], name: str, default, cast, *, minimum=None, maximum=None):
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = cast(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class ASOSTSettings:
    """Validated, immutable settings snapshot for one ASOST run.

    ``max_failovers`` may be zero to explicitly disable failover.  Timeout,
    output-token and budget values must be greater than zero.
    """

    models: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 300.0
    max_output_tokens: int = 8192
    temperature: float = 0.2
    max_failovers: int = 2
    run_request_budget: int = 100
    book_token_budget: int = 2_000_000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ASOSTSettings":
        env = os.environ if environ is None else environ
        default_model = env.get("ASOST_GEMINI_MODEL", DEFAULT_MODEL).strip()
        if not default_model:
            raise ValueError("ASOST_GEMINI_MODEL must not be empty")
        models = {}
        for task in TASKS:
            value = env.get(f"ASOST_GEMINI_MODEL_{task.upper()}", default_model).strip()
            if not value:
                raise ValueError(f"ASOST_GEMINI_MODEL_{task.upper()} must not be empty")
            models[task] = value
        return cls(
            models=models,
            timeout_seconds=_number(env, "ASOST_GEMINI_TIMEOUT_SECONDS", 300.0, float, minimum=0.001),
            max_output_tokens=_number(env, "ASOST_GEMINI_MAX_OUTPUT_TOKENS", 8192, int, minimum=1),
            temperature=_number(env, "ASOST_GEMINI_TEMPERATURE", 0.2, float, minimum=0.0, maximum=2.0),
            max_failovers=_number(env, "ASOST_GEMINI_MAX_FAILOVERS", 2, int, minimum=0),
            run_request_budget=_number(env, "ASOST_GEMINI_RUN_REQUEST_BUDGET", 100, int, minimum=1),
            book_token_budget=_number(env, "ASOST_GEMINI_BOOK_TOKEN_BUDGET", 2_000_000, int, minimum=1),
        )

    def model_for(self, task: str) -> str:
        """Return the configured model, rejecting unknown task names."""
        try:
            return self.models[task]
        except KeyError as exc:
            raise ValueError(f"unknown ASOST task: {task!r}") from exc
