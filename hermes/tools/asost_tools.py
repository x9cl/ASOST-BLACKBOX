"""ASOST tools for Hermes Agent — translation, critique, and memory.

Self-registering tool module: imported automatically by
``tools/registry.py::discover_builtin_tools()`` because it contains a
top-level ``registry.register(...)`` call (same pattern as memory_tool.py).

Placeholder implementations — ready to be filled in later:
- asost_translate_text: delegates to the ASOST OpenRouter engine
  (assost-main/openrouter_engine.py, model stealth/ox-alpha) via dynamic import.
- asost_memory_get / asost_memory_set: JSON key/value store at
  /opt/data/projects/assost/asost_memory.json

(النقد يتم داخل منظومة ASOST عبر وكلاء critic_light/critic_deep — لا أداة critique هنا.)
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from tools.registry import registry

logger = __import__("logging").getLogger(__name__)

# Resolve the integration from this checkout unless deployment overrides it.
_PROJECT_ROOT = Path(os.environ.get(
    "ASOST_PROJECT_ROOT", Path(__file__).resolve().parents[2]
)).expanduser().resolve()
_ASOST_MAIN = str(_PROJECT_ROOT / "assost-main")
_MEMORY_PATH = Path(os.environ.get(
    "ASOST_MEMORY_PATH", _PROJECT_ROOT / "asost_memory.json"
)).expanduser().resolve()

_engine = None          # cached EnhancedOpenRouterAPI instance
_engine_lock = threading.Lock()
_memory_lock = threading.Lock()


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


def asost_memory_get(key: str, book_id: str = "", namespace: str = "agent") -> str:
    """Read ``key`` from the ASOST JSON memory file. Returns '' when absent."""
    if book_id:
        if str(_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_PROJECT_ROOT))
        from asost.config import ASOSTSettings
        from asost.store import ASOSTStore

        value = ASOSTStore(ASOSTSettings.load().state_db_path).memory_get(
            book_id, namespace, key, ""
        )
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    try:
        data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError):
        return ""
    value = data.get(key, "")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def asost_memory_set(key: str, value: str, book_id: str = "",
                     namespace: str = "agent") -> str:
    """Atomically merge ``key`` into the ASOST JSON memory file."""
    if book_id:
        if str(_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_PROJECT_ROOT))
        from asost.config import ASOSTSettings
        from asost.store import ASOSTStore

        try:
            stored = json.loads(value)
        except ValueError:
            stored = value
        ASOSTStore(ASOSTSettings.load().state_db_path).memory_put(
            book_id, namespace, key, stored
        )
        return f"saved: {book_id}/{namespace}/{key}"
    try:
        with _memory_lock:
            try:
                data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (FileNotFoundError, OSError, ValueError):
                data = {}
            try:
                stored = json.loads(value)
            except ValueError:
                stored = value
            data[key] = stored
            _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{_MEMORY_PATH.name}.",
                dir=str(_MEMORY_PATH.parent),
                text=True,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, _MEMORY_PATH)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
                raise
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
                "book_id": {"type": "string", "description": "Required book namespace."},
                "namespace": {"type": "string", "description": "Agent role or memory class."},
            },
            "required": ["key"],
        },
    },
    handler=lambda args, **kw: asost_memory_get(
        key=args.get("key", ""), book_id=args.get("book_id", ""),
        namespace=args.get("namespace", "agent")),
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
                "book_id": {"type": "string", "description": "Required book namespace."},
                "namespace": {"type": "string", "description": "Agent role or memory class."},
            },
            "required": ["key", "value"],
        },
    },
    handler=lambda args, **kw: asost_memory_set(
        key=args.get("key", ""), value=args.get("value", ""),
        book_id=args.get("book_id", ""), namespace=args.get("namespace", "agent")
    ),
    emoji="💾",
)
