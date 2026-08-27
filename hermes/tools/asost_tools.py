"""ASOST tools for Hermes Agent — translation, critique, and memory.

Self-registering tool module: imported automatically by
``tools/registry.py::discover_builtin_tools()`` because it contains a
top-level ``registry.register(...)`` call (same pattern as memory_tool.py).

Implementations:
- asost_translate_text: delegates to the ASOST Gemini engine using a leased
  credential from Hermes' pool.
- asost_memory_get / asost_memory_set: JSON key/value store at
  /opt/data/projects/assost/asost_memory.json

(النقد يتم داخل منظومة ASOST عبر وكلاء critic_light/critic_deep — لا أداة critique هنا.)
"""

import json
import sys
from pathlib import Path

from tools.registry import registry

logger = __import__("logging").getLogger(__name__)

# Dynamic import path for the ASOST engine
_ASOST_MAIN = str(Path(__file__).resolve().parents[2] / "assost-main")
_MEMORY_PATH = Path("/opt/data/projects/assost/asost_memory.json")


def _get_engine(api_keys):
    """Construct an ASOST Gemini client for one tool invocation.

    Async HTTP clients are deliberately not cached here: the registry can run
    handlers on different worker loops, and a cached aiohttp session would be
    bound to whichever loop happened to make the first call.
    """
    if _ASOST_MAIN not in sys.path:
        sys.path.insert(0, _ASOST_MAIN)
    from PF import CompleteTranslationEngine, EnhancedGeminiAPI

    api = EnhancedGeminiAPI(api_keys)
    return api, CompleteTranslationEngine(api)


def _get_pool():
    """Load the Hermes credential pool lazily to keep tool discovery cheap."""
    from agent.credential_pool import load_pool

    return load_pool("gemini")


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

async def _call_with_pool(args: dict, **_kwargs) -> str:
    """Translate with a leased Hermes Gemini credential.

    Cleanup and lease release live in the same ``finally`` block so task
    cancellation cannot strand either the aiohttp client or the pool slot.
    """
    pool = _get_pool()
    lease_id = pool.acquire_lease()
    if lease_id is None:
        raise RuntimeError("No Gemini credential is available")

    api = None
    try:
        entry = next((item for item in pool.entries() if item.id == lease_id), None)
        if entry is None or not entry.runtime_api_key:
            raise RuntimeError("The leased Gemini credential could not be resolved")
        api, translator = _get_engine([entry.runtime_api_key])
        result, _elapsed, _key = await translator.translate_with_completion_guarantee(
            text=args.get("text", ""), context=args.get("context", "")
        )
        return result or ""
    finally:
        try:
            if api is not None:
                await api.cleanup()
        finally:
            pool.release_lease(lease_id)


async def asost_translate_text(
    text: str, context: str = "", engine: str = "auto"
) -> str:
    """Translate ``text`` through the same async, lease-safe tool path."""
    return await _call_with_pool({"text": text, "context": context, "engine": engine})


def asost_memory_get(key: str) -> str:
    """Read ``key`` from the ASOST JSON memory file. Returns '' when absent."""
    try:
        data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError):
        return ""
    value = data.get(key, "")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def asost_memory_set(key: str, value: str) -> str:
    """Write ``key`` into the ASOST JSON memory file (merged write)."""
    try:
        try:
            data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, OSError, ValueError):
            data = {}
        # Try to store structured values when they parse as JSON
        try:
            stored = json.loads(value)
        except ValueError:
            stored = value
        data[key] = stored
        _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MEMORY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return f"saved: {key}"
    except OSError as exc:
        return f"error: {exc}"


# ---------------------------------------------------------------------------
# Registry registration (mirrors tools/memory_tool.py)
# ---------------------------------------------------------------------------

registry.register(
    name="asost_translate_text",
    toolset="asost_translate",
    schema={
        "description": (
            "Translate text to Arabic using the ASOST translation engine "
            "with a pooled Gemini credential."
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
    handler=_call_with_pool,
    is_async=True,
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
            },
            "required": ["key"],
        },
    },
    handler=lambda args, **kw: asost_memory_get(key=args.get("key", "")),
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
            },
            "required": ["key", "value"],
        },
    },
    handler=lambda args, **kw: asost_memory_set(
        key=args.get("key", ""), value=args.get("value", "")
    ),
    emoji="💾",
)
