"""Portable runtime paths and limits for the ASOST integration layer.

This module deliberately contains no Hermes imports.  Both the standalone
ASOST code and Hermes tools can therefore use the same configuration without
creating a dependency cycle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class ASOSTSettings:
    """Resolved paths and safety limits shared by ASOST and Hermes."""

    project_root: Path
    hermes_home: Path
    memory_path: Path
    gemini_max_input_chars: int
    gemini_pool_failovers: int
    max_upload_bytes: int
    max_agent_iterations: int
    state_db_path: Path
    gemini_model: str
    gemini_timeout_seconds: int
    max_agent_calls_per_run: int

    @classmethod
    def load(cls) -> "ASOSTSettings":
        default_root = Path(__file__).resolve().parent.parent
        project_root = Path(
            os.environ.get("ASOST_PROJECT_ROOT", str(default_root))
        ).expanduser().resolve()
        hermes_home = Path(
            os.environ.get("HERMES_HOME", str(project_root / "hermes-home"))
        ).expanduser().resolve()
        memory_path = Path(
            os.environ.get("ASOST_MEMORY_PATH", str(project_root / "asost_memory.json"))
        ).expanduser().resolve()
        return cls(
            project_root=project_root,
            hermes_home=hermes_home,
            memory_path=memory_path,
            gemini_max_input_chars=_positive_int("ASOST_GEMINI_MAX_INPUT_CHARS", 20_000),
            gemini_pool_failovers=_positive_int("ASOST_GEMINI_POOL_FAILOVERS", 3),
            max_upload_bytes=_positive_int("ASOST_MAX_UPLOAD_BYTES", 100 * 1024 * 1024),
            max_agent_iterations=_positive_int("ASOST_MAX_AGENT_ITERATIONS", 12),
            state_db_path=Path(
                os.environ.get(
                    "ASOST_STATE_DB", str(project_root / "asost_state.db")
                )
            ).expanduser().resolve(),
            gemini_model=os.environ.get("ASOST_GEMINI_MODEL", "gemini-3.5-flash"),
            gemini_timeout_seconds=_positive_int("ASOST_GEMINI_TIMEOUT_SECONDS", 300),
            max_agent_calls_per_run=_positive_int("ASOST_MAX_AGENT_CALLS_PER_RUN", 1000),
        )

    @property
    def asost_main(self) -> Path:
        return self.project_root / "assost-main"


settings = ASOSTSettings.load()
