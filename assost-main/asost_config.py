"""Runtime configuration for ASOST model-backed tasks.

The provider layer deliberately receives these values rather than owning task
defaults.  Deployments may replace the built-in policy map with JSON from
``ASOST_GEMINI_POLICIES`` or ``ASOST_GEMINI_POLICY_FILE``.
"""

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class GeminiTaskPolicy:
    """Complete generation policy for one logical ASOST task."""

    model: str
    temperature: float
    max_output_tokens: int
    timeout: float
    request_type: str
    fallback_models: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("GeminiTaskPolicy.model cannot be empty")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        object.__setattr__(self, "fallback_models", tuple(self.fallback_models))

    @property
    def models(self) -> Tuple[str, ...]:
        """Models in failover order, with duplicates removed."""
        return tuple(dict.fromkeys((self.model, *self.fallback_models)))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "GeminiTaskPolicy":
        data = dict(values)
        data["fallback_models"] = tuple(data.get("fallback_models", ()))
        return cls(**data)


DEFAULT_GEMINI_POLICIES: Dict[str, GeminiTaskPolicy] = {
    "translation": GeminiTaskPolicy(
        model="gemini-3.5-flash", temperature=0.05,
        max_output_tokens=16384, timeout=300, request_type="translation",
    ),
    "critique": GeminiTaskPolicy(
        model="gemini-3.5-flash", temperature=0.0,
        max_output_tokens=4096, timeout=120, request_type="critique",
    ),
}


def load_gemini_task_policies(
    environ: Mapping[str, str] = os.environ,
) -> Dict[str, GeminiTaskPolicy]:
    """Load task policies, overlaying defaults with deployment configuration.

    JSON can be supplied inline or through a file.  Each task entry is a full
    policy or a partial override.  In particular, ``fallback_models`` can be
    changed operationally without a source-code edit.
    """
    raw = environ.get("ASOST_GEMINI_POLICIES", "").strip()
    path = environ.get("ASOST_GEMINI_POLICY_FILE", "").strip()
    if raw and path:
        raise ValueError("set only one of ASOST_GEMINI_POLICIES and ASOST_GEMINI_POLICY_FILE")
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    overrides = json.loads(raw) if raw else {}
    if not isinstance(overrides, dict):
        raise ValueError("Gemini policy configuration must be a JSON object")

    policies = dict(DEFAULT_GEMINI_POLICIES)
    for task, values in overrides.items():
        if not isinstance(values, dict):
            raise ValueError(f"policy for {task!r} must be a JSON object")
        if task in policies:
            base = policies[task]
            policies[task] = replace(
                base,
                **{**values, "fallback_models": tuple(
                    values.get("fallback_models", base.fallback_models)
                )},
            )
        else:
            policies[task] = GeminiTaskPolicy.from_mapping(values)
    return policies


class ASOSTSettings:
    """ASOST configuration boundary used by orchestration/composition roots."""

    def __init__(self, gemini_policies: Mapping[str, GeminiTaskPolicy] = None):
        self.gemini_policies = dict(gemini_policies or load_gemini_task_policies())

    def gemini_policy(self, task: str) -> GeminiTaskPolicy:
        try:
            return self.gemini_policies[task]
        except KeyError as exc:
            raise KeyError(f"no Gemini policy configured for task {task!r}") from exc

    def policy_for_request(self, request_type: str) -> GeminiTaskPolicy:
        """Resolve a policy while preserving legacy PF request subtypes."""
        if request_type in self.gemini_policies:
            return self.gemini_policies[request_type]
        return replace(self.gemini_policy("translation"), request_type=request_type)
