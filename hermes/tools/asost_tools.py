"""ASOST tools for Hermes Agent — translation, critique, and memory.

Self-registering tool module: imported automatically by
``tools/registry.py::discover_builtin_tools()`` because it contains a
top-level ``registry.register(...)`` call (same pattern as memory_tool.py).

Placeholder implementations — ready to be filled in later:
- asost_translate_text: delegates to the ASOST OpenRouter engine
  (assost-main/openrouter_engine.py, model stealth/ox-alpha) via dynamic import.
- asost_memory_get / asost_memory_set: namespaced SQLite repository in WAL mode

(النقد يتم داخل منظومة ASOST عبر وكلاء critic_light/critic_deep — لا أداة critique هنا.)
"""

import asyncio
import sys
import threading
from asost.memory import MemoryNamespace, SQLiteMemoryRepository

from tools.registry import registry

logger = __import__("logging").getLogger(__name__)

# Dynamic import path for the ASOST engine
_ASOST_MAIN = "/opt/data/projects/assost/assost-main"
_engine = None          # cached EnhancedOpenRouterAPI instance
_engine_lock = threading.Lock()


def _get_engine():
    """Lazily import and cache the ASOST OpenRouter engine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if _ASOST_MAIN not in sys.path:
                    sys.path.insert(0, _ASOST_MAIN)
                from openrouter_engine import EnhancedOpenRouterAPI  # noqa
                _engine = EnhancedOpenRouterAPI()
    return _engine


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def asost_translate_text(text: str, context: str = "", engine: str = "auto") -> str:
    """Translate ``text`` to Arabic via the ASOST OpenRouter engine."""
    api = _get_engine()
    result = asyncio.run(api.translate_text(text=text, context=context))
    return result or ""


def _namespace(book_id, run_id, agent_role, chapter_id, segment_id):
    return MemoryNamespace(book_id, run_id, agent_role, chapter_id, segment_id)

def asost_memory_get(key: str, book_id: str, run_id: str, agent_role: str,
                     chapter_id: str, segment_id: str) -> str:
    """Read a namespaced value from the shared repository."""
    import json
    value = SQLiteMemoryRepository().get(
        _namespace(book_id, run_id, agent_role, chapter_id, segment_id), key, "")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def asost_memory_set(key: str, value: str, book_id: str, run_id: str, agent_role: str,
                     chapter_id: str, segment_id: str) -> str:
    """Write a namespaced value into the shared repository."""
    import json
    try:
        stored = json.loads(value)
    except ValueError:
        stored = value
    SQLiteMemoryRepository().put(
        _namespace(book_id, run_id, agent_role, chapter_id, segment_id), key, stored)
    return f"saved: {key}"


# ---------------------------------------------------------------------------
# Registry registration (mirrors tools/memory_tool.py)
# ---------------------------------------------------------------------------

registry.register(
    name="asost_translate_text",
    toolset="asost_translate",
    schema={
        "description": (
            "Translate text to Arabic using the ASOST translation engine "
            "(ox-alpha via OpenRouter)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The source text to translate.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context/genre hints to improve quality.",
                },
                "engine": {
                    "type": "string",
                    "description": "Engine selector; currently only 'auto' is supported.",
                },
            },
            "required": ["text"],
        },
    },
    handler=lambda args, **kw: asost_translate_text(
        text=args.get("text", ""),
        context=args.get("context", ""),
        engine=args.get("engine", "auto"),
    ),
    emoji="🌍",
)

registry.register(
    name="asost_memory_get",
    toolset="asost_memory",
    schema={
        "description": "Read a value from ASOST persistent memory (ترجماني ميموري).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to read."},
                "book_id": {"type": "string"}, "run_id": {"type": "string"},
                "agent_role": {"type": "string"}, "chapter_id": {"type": "string"},
                "segment_id": {"type": "string"},
            },
            "required": ["key", "book_id", "run_id", "agent_role", "chapter_id", "segment_id"],
        },
    },
    handler=lambda args, **kw: asost_memory_get(**{
        k: args.get(k, "") for k in ("key", "book_id", "run_id", "agent_role", "chapter_id", "segment_id")}),
    emoji="🗂️",
)

registry.register(
    name="asost_memory_set",
    toolset="asost_memory",
    schema={
        "description": "Write a value into ASOST persistent memory (ترجماني ميموري).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key."},
                "value": {"type": "string", "description": "Value to store."},
                "book_id": {"type": "string"}, "run_id": {"type": "string"},
                "agent_role": {"type": "string"}, "chapter_id": {"type": "string"},
                "segment_id": {"type": "string"},
            },
            "required": ["key", "value", "book_id", "run_id", "agent_role", "chapter_id", "segment_id"],
        },
    },
    handler=lambda args, **kw: asost_memory_set(**{
        k: args.get(k, "") for k in ("key", "value", "book_id", "run_id", "agent_role", "chapter_id", "segment_id")}),
    emoji="💾",
)
