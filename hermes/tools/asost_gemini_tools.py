"""Hermes-facing adapter for the shared ASOST Gemini configuration.

This module owns no process-global settings snapshot.  Call
``settings_for_run()`` when an ASOST run starts and pass that returned snapshot
through the run.  Consequently environment configuration is **reloadable
between runs**, while deliberately remaining stable during a run.

The configuration implementation lives in :mod:`asost.settings` and imports
no Hermes modules, so non-Hermes entry points use exactly the same validation.
"""

from __future__ import annotations

from collections.abc import Mapping

from asost.settings import ASOSTSettings


def settings_for_run(environ: Mapping[str, str] | None = None) -> ASOSTSettings:
    """Load and validate a fresh configuration snapshot for an ASOST run."""
    return ASOSTSettings.from_env(environ)


__all__ = ["ASOSTSettings", "settings_for_run"]
