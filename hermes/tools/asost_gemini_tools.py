"""Gemini literary services exposed as bounded tools to Hermes agents.

Gemini is intentionally a tool, not the ASOST orchestrator.  Credentials are
selected and cooled down by Hermes' existing credential pool; this module does
not maintain a second key list or persist secrets.
"""

from __future__ import annotations

import asyncio
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


def _settings() -> tuple[int, int]:
    max_chars = int(os.environ.get("ASOST_GEMINI_MAX_INPUT_CHARS", "20000"))
    failovers = int(os.environ.get("ASOST_GEMINI_POOL_FAILOVERS", "3"))
    if max_chars < 1 or failovers < 1:
        raise ValueError("ASOST Gemini limits must be greater than zero")
    return max_chars, failovers


def _build_prompt(task: str, text: str, context: str, glossary: str) -> str:
    sections = []
    if context.strip():
        sections.append("REFERENCE CONTEXT (do not translate):\n" + context.strip())
    if glossary.strip():
        sections.append("MANDATORY GLOSSARY:\n" + glossary.strip())
    label = "SOURCE TEXT" if task != "critique" else "SOURCE AND ARABIC DRAFT"
    sections.append(f"{label}:\n{text.strip()}")
    return "\n\n---\n\n".join(sections)


async def _call_with_pool(
    task: str,
    text: str,
    context: str = "",
    glossary: str = "",
) -> Dict[str, Any]:
    if task not in _TASK_INSTRUCTIONS:
        raise ValueError(f"Unsupported Gemini task: {task}")
    max_chars, max_failovers = _settings()
    if not text.strip():
        raise ValueError("Gemini tool input text is empty")
    if len(text) > max_chars:
        raise ValueError(f"Gemini tool input exceeds {max_chars} characters")

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
        api = EnhancedGeminiAPI(api_keys=[credential.runtime_api_key])
        try:
            output, latency, _key_used = await api.make_precision_request(
                _build_prompt(task, text, context, glossary),
                system_instruction=_TASK_INSTRUCTIONS[task],
                temperature=0.2,
                request_type={
                    "translate": "translation",
                    "critique": "quality_review",
                    "terminology": "terminology_extraction",
                    "summarize": "quality_review",
                }[task],
            )
            if not output:
                raise RuntimeError("Gemini returned an empty response")
            return {
                "task": task,
                "output": output,
                "provider": "gemini",
                "credential_id": credential.id,
                "latency_seconds": round(float(latency), 3),
            }
        except Exception as exc:
            last_error = exc
            pool.mark_exhausted_and_rotate(
                status_code=None,
                credential_id=credential.id,
                failure_reason="transient",
                error_context={"message": str(exc)[:200]},
            )
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


def asost_gemini_task(
    task: str,
    text: str,
    context: str = "",
    glossary: str = "",
) -> str:
    """Run one bounded literary task and return structured provenance JSON."""
    result = asyncio.run(_call_with_pool(task, text, context, glossary))
    return json.dumps(result, ensure_ascii=False)


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
            },
            "required": ["task", "text"],
        },
    },
    handler=lambda args, **kw: asost_gemini_task(
        task=args.get("task", ""),
        text=args.get("text", ""),
        context=args.get("context", ""),
        glossary=args.get("glossary", ""),
    ),
    emoji="♊",
)
