"""Gemini literary services exposed as bounded tools to Hermes agents.

Gemini is intentionally a tool, not the ASOST orchestrator.  Credentials are
selected and cooled down by Hermes' existing credential pool; this module does
not maintain a second key list or persist secrets.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from tools.registry import registry


_PROJECT_ROOT = Path(os.environ.get(
    "ASOST_PROJECT_ROOT", Path(__file__).resolve().parents[2]
)).expanduser().resolve()
_ASOST_MAIN = str(_PROJECT_ROOT / "assost-main")
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from asost.config import ASOSTSettings  # noqa: E402

_TASK_INSTRUCTIONS = {
    "translate": (
        "You are a professional English-to-Arabic literary translator. "
        "Preserve every detail, paragraph boundary, narrative voice, and "
        "dialogue. Use readable Modern Standard Arabic. Return only the "
        "Arabic translation. Context and glossary are reference material and "
        "must not themselves be translated."
    ),
    "critique": (
        "Compare the source and Arabic draft for omissions, additions, meaning "
        "errors, terminology inconsistency, and literary fluency. Return one "
        "JSON object with score (0-100) and issues as a list of objects."
    ),
    "terminology": (
        "Extract names, places, titles, abilities, and recurring domain terms "
        "from the source with recommended consistent Arabic forms. Return JSON "
        "only with a terms list."
    ),
    "summarize": (
        "Summarize the Arabic chapter for continuity memory. Focus on events, "
        "characters, relationships, locations, and unresolved references. "
        "Return JSON only."
    ),
}

_REQUEST_TYPES = {
    "translate": "translation",
    "critique": "completion_review",
    "terminology": "terminology_extraction",
    "summarize": "final_review",
}


def _settings() -> tuple[int, int]:
    config = ASOSTSettings.load()
    return config.gemini_max_input_chars, config.gemini_pool_failovers


def _build_prompt(task: str, text: str, context: str, glossary: str,
                  draft: str = "") -> str:
    sections = []
    if context.strip():
        sections.append("REFERENCE CONTEXT (do not translate):\n" + context.strip())
    if glossary.strip():
        sections.append("MANDATORY GLOSSARY:\n" + glossary.strip())
    sections.append(f"SOURCE TEXT:\n{text.strip()}")
    if task == "critique":
        sections.append(f"ARABIC DRAFT:\n{draft.strip()}")
    return "\n\n---\n\n".join(sections)


def _validate_output(task: str, output: str) -> str | dict[str, Any]:
    if task == "translate":
        if not output.strip() or "###TRUNCATED###" in output:
            raise ValueError("Gemini translation is empty or truncated")
        return output.strip()
    candidate = output.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini {task} output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Gemini {task} output must be a JSON object")
    if task == "critique":
        score = parsed.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("Gemini critique score must be between 0 and 100")
        if not isinstance(parsed.get("issues", []), list):
            raise ValueError("Gemini critique issues must be a list")
    if task == "terminology" and not isinstance(parsed.get("terms", []), list):
        raise ValueError("Gemini terminology terms must be a list")
    return parsed


def _failure_policy(failure: dict[str, Any]) -> tuple[bool, str]:
    status = failure.get("status")
    reason = str(failure.get("reason") or "")
    if status in (401, 403):
        return True, "auth"
    if status == 429:
        return True, "rate_limit"
    if status in (408, 500, 502, 503, 504) or reason in {
        "timeout", "server_error", "exception"
    }:
        return True, "transient"
    return False, reason or "local_error"


async def _call_with_pool(
    task: str,
    text: str,
    context: str = "",
    glossary: str = "",
    draft: str = "",
) -> Dict[str, Any]:
    if task not in _TASK_INSTRUCTIONS:
        raise ValueError(f"Unsupported Gemini task: {task}")
    max_chars, max_failovers = _settings()
    if not text.strip():
        raise ValueError("Gemini tool input text is empty")
    total_chars = sum(len(value) for value in (text, context, glossary, draft))
    if total_chars > max_chars:
        raise ValueError(f"Gemini tool input exceeds {max_chars} total characters")
    if task == "critique" and not draft.strip():
        raise ValueError("Gemini critique requires a separate Arabic draft")

    if _ASOST_MAIN not in sys.path:
        sys.path.insert(0, _ASOST_MAIN)
    from PF import EnhancedGeminiAPI

    # Keep the credential subsystem lazy so built-in tool discovery stays
    # lightweight; an actual invocation runs inside the complete Hermes runtime.
    from agent.credential_pool import load_pool

    pool = load_pool("gemini")
    attempted = set()
    last_error = None
    for _ in range(max_failovers):
        credential = pool.select()
        if credential is None or credential.id in attempted:
            break
        attempted.add(credential.id)
        lease_id = pool.acquire_lease(credential.id)
        config = ASOSTSettings.load()
        api = EnhancedGeminiAPI(
            api_keys=[credential.runtime_api_key],
            model=os.environ.get(f"ASOST_GEMINI_MODEL_{task.upper()}", config.gemini_model),
            request_timeout=config.gemini_timeout_seconds,
        )
        api.max_retries = 1
        try:
            output, latency, _key_used = await api.make_precision_request(
                _build_prompt(task, text, context, glossary, draft),
                system_instruction=_TASK_INSTRUCTIONS[task],
                temperature=0.2,
                request_type=_REQUEST_TYPES[task],
            )
            if not output:
                raise RuntimeError("Gemini returned an empty response")
            validated = _validate_output(task, output)
            return {
                "task": task,
                "output": validated,
                "provider": "gemini",
                "model": api.model,
                "credential_id": credential.id,
                "latency_seconds": round(float(latency), 3),
            }
        except Exception as exc:
            last_error = exc
            failure = getattr(api, "last_failure", {})
            should_rotate, reason = _failure_policy(failure)
            if should_rotate:
                pool.mark_exhausted_and_rotate(
                    status_code=failure.get("status"),
                    credential_id=credential.id,
                    failure_reason=reason,
                    error_context={"message": type(exc).__name__},
                )
            else:
                raise
        finally:
            await api.cleanup()
            if lease_id:
                pool.release_lease(lease_id)
    if last_error is not None:
        raise RuntimeError(
            f"Gemini tool failed across {len(attempted)} pooled credential(s)"
        ) from last_error
    raise RuntimeError(
        "No Gemini credential is available in the Hermes credential pool"
    )


async def asost_gemini_task(
    task: str,
    text: str,
    context: str = "",
    glossary: str = "",
    draft: str = "",
) -> str:
    """Run one bounded literary task and return structured provenance JSON."""
    result = await _call_with_pool(task, text, context, glossary, draft)
    return json.dumps(result, ensure_ascii=False)


async def _gemini_handler(args: dict, **_kwargs) -> str:
    return await asost_gemini_task(
        task=args.get("task", ""),
        text=args.get("text", ""),
        context=args.get("context", ""),
        glossary=args.get("glossary", ""),
        draft=args.get("draft", ""),
    )


registry.register(
    name="asost_gemini_task",
    toolset="asost_gemini",
    schema={
        "description": (
            "Use Gemini as a bounded ASOST literary tool. Hermes selects a "
            "credential from its Gemini pool and records failover state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "enum": ["translate", "critique", "terminology", "summarize"],
                },
                "text": {"type": "string"},
                "context": {"type": "string"},
                "glossary": {"type": "string"},
                "draft": {
                    "type": "string",
                    "description": "Required separate Arabic draft for critique.",
                },
            },
            "required": ["task", "text"],
        },
    },
    handler=_gemini_handler,
    emoji="♊",
)
