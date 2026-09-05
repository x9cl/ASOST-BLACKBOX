"""Bounded routing plans and auditable execution traces for ASOST chunks."""
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Dict, List, Optional


VALID_ROUTES = {"agent", "gemini", "openrouter_translation"}


@dataclass(frozen=True)
class ExecutionPlan:
    """The Translation Planner's immutable decision for one source chunk."""

    source_hash: str
    route: str
    max_tool_calls: int
    allow_provider_fallback: bool
    rationale: str

    def __post_init__(self):
        if self.route not in VALID_ROUTES:
            raise ValueError(f"unsupported translation route: {self.route}")
        if not 0 <= self.max_tool_calls <= 2:
            raise ValueError("max_tool_calls must be between 0 and 2")
        if self.route == "agent" and self.max_tool_calls:
            raise ValueError("agent route cannot reserve tool calls")
        if self.route != "agent" and self.max_tool_calls < 1:
            raise ValueError("tool routes require at least one tool call")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TranslationPlanner:
    """Select exactly one bounded route rather than delegating routing to agents."""

    @staticmethod
    def plan(source: str, *, requires_gemini: bool = False,
             requires_translation_tool: bool = False,
             sensitive: bool = False) -> ExecutionPlan:
        if requires_gemini and requires_translation_tool:
            raise ValueError("a chunk cannot require two translation routes")
        source_hash = sha256(source.encode("utf-8")).hexdigest()
        if requires_gemini:
            route, calls, reason = "gemini", 1, "explicit Gemini capability requirement"
        elif requires_translation_tool:
            route, calls, reason = (
                "openrouter_translation", 1, "explicit translation-tool requirement")
        else:
            route, calls, reason = "agent", 0, "literary translation is within agent capability"
        return ExecutionPlan(
            source_hash=source_hash,
            route=route,
            max_tool_calls=calls,
            allow_provider_fallback=not sensitive,
            rationale=reason,
        )


class ToolCallBudgetExceeded(RuntimeError):
    pass


class InvalidExecutionTrace(ValueError):
    pass


@dataclass
class ExecutionTrace:
    source_hash: str
    events: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, stage: str, actor: str, *, model: Optional[str] = None,
            tool: Optional[str] = None, justification: Optional[str] = None):
        event = {"stage": stage, "actor": actor}
        for key, value in (("model", model), ("tool", tool),
                           ("justification", justification)):
            if value:
                event[key] = value
        self.events.append(event)

    def validate(self):
        full = [e for e in self.events if e.get("stage") == "full_translation"]
        if len(full) > 1 and any(not e.get("justification") for e in full[1:]):
            raise InvalidExecutionTrace(
                "duplicate full translations for the same source hash require justification")
        return True

    def to_dict(self):
        self.validate()
        return {"source_hash": self.source_hash, "events": list(self.events)}


class Supervisor:
    """Enforce the planner's per-chunk tool budget and fallback policy."""

    def __init__(self, plan: ExecutionPlan):
        self.plan = plan
        self.tool_calls = 0

    def record_tool_call(self, tool: str):
        if self.tool_calls >= self.plan.max_tool_calls:
            raise ToolCallBudgetExceeded(
                f"tool-call budget exhausted for {self.plan.source_hash}: "
                f"{self.tool_calls}/{self.plan.max_tool_calls}")
        self.tool_calls += 1
        return self.tool_calls

    def require_fallback_allowed(self):
        if not self.plan.allow_provider_fallback:
            raise PermissionError("provider fallback is forbidden by ExecutionPlan")

