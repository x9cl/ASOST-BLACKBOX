"""api.py — FastAPI router لربط منظومة ASOST-agents بالداشبورد.

يُضاف إلى server.py بسطرين فقط:
    from asost.api import router as asost_router
    app.include_router(asost_router)

Endpoints:
    POST /api/asost/translate-page  {page_num, src_text, context} → {job_id}
    GET  /api/asost/status/{job_id} → حالة المهمة + النتيجة
    GET  /api/asost/agents          → الوكلاء الستة وهويتهم من identity.yaml
    GET  /api/asost/memory          → ملخص عددي آمن للذاكرة
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

ASOST_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ASOST_DIR / "agents"
MEMORY_PATH = Path("/opt/data/projects/assost/asost_memory.json")

MAX_SRC_TEXT_CHARS = 20000
MAX_JOBS = 50  # نحتفظ بآخر 50 مهمة فقط (تنظيف الأقدم عند الإضافة)

router = APIRouter(prefix="/api/asost", tags=["asost"])

_jobs: dict = {}
_lock = threading.Lock()

ROLES = frozenset({"operator", "reviewer", "observer", "admin"})
READ_ROLES = ROLES
WRITE_ROLES = frozenset({"operator", "admin"})
ROLE_ALIASES = {
    "read-only observer": "observer",
    "read-only-observer": "observer",
    "read_only_observer": "observer",
}
SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "credential", "credentials",
    "password", "secret", "token", "access_token", "refresh_token",
})


def _configured_tokens() -> dict[str, str]:
    """Load token-to-role mappings without ever putting tokens in responses."""
    raw = os.environ.get("ASOST_AUTH_TOKENS", "")
    try:
        configured = json.loads(raw) if raw else {}
    except ValueError as exc:
        raise HTTPException(503, "إعداد المصادقة على الخادم غير صالح") from exc
    if not isinstance(configured, dict):
        raise HTTPException(503, "إعداد المصادقة على الخادم غير صالح")

    tokens = {}
    for token, configured_role in configured.items():
        role = str(configured_role).strip().lower()
        role = ROLE_ALIASES.get(role, role)
        if token and role in ROLES:
            tokens[str(token)] = role
    # Backwards compatibility: the old write token receives admin privileges.
    legacy = os.environ.get("ASOST_API_TOKEN", "")
    if legacy:
        tokens.setdefault(legacy, "admin")
    if not tokens:
        raise HTTPException(503, "المصادقة معطلة: لم تُضبط توكنات ASOST")
    return tokens


def _authorize(token: str | None, allowed_roles: frozenset[str]) -> str:
    if not token:
        raise HTTPException(401, "بيانات المصادقة مفقودة")
    role = next(
        (role for expected, role in _configured_tokens().items()
         if hmac.compare_digest(token, expected)),
        None,
    )
    if role is None:
        raise HTTPException(401, "بيانات المصادقة غير صحيحة")
    if role not in allowed_roles:
        raise HTTPException(403, "ليست لديك الصلاحية المطلوبة")
    return role


def _check_write_auth(x_asost_token: str | None):
    """Require an operator or administrator for a mutating operation."""
    return _authorize(x_asost_token, WRITE_ROLES)


def _redact_credentials(value: object) -> object:
    """Remove credential values from structured job results."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS
            else _redact_credentials(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_credentials(item) for item in value]
    return value


def _get_orchestrator():
    from orchestrator import ASOSTOrchestrator
    return ASOSTOrchestrator()


# ------------------------------------------------------------- translate --
class TranslateRequest(BaseModel):
    page_num: int
    src_text: str
    context: str = ""


def _run_job(job_id: str, page_num: int, src_text: str, context: str):
    with _lock:
        _jobs[job_id]["status"] = "running"
    try:
        orch = _get_orchestrator()
        result = orch.translate_page(page_num, src_text, context)
        with _lock:
            _jobs[job_id].update(status="done", result=result)
    except Exception:  # noqa: BLE001
        with _lock:
            _jobs[job_id].update(status="error", error="تعذر إكمال المهمة")


@router.post("/translate-page")
async def translate_page(
    req: TranslateRequest,
    background: BackgroundTasks,
    x_asost_token: str | None = Header(default=None),
):
    _check_write_auth(x_asost_token)
    if req.page_num < 1:
        raise HTTPException(422, f"page_num غير صالح: {req.page_num}")
    if len(req.src_text) > MAX_SRC_TEXT_CHARS:
        raise HTTPException(
            422, f"src_text أكبر من الحد ({len(req.src_text)} > "
                 f"{MAX_SRC_TEXT_CHARS} حرفاً)")
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        # تنظيف: أبقِ آخر MAX_JOBS مهمة فقط
        while len(_jobs) >= MAX_JOBS:
            oldest = min(_jobs, key=lambda j: _jobs[j].get("_seq", 0))
            del _jobs[oldest]
        job = {"status": "queued", "page_num": req.page_num,
               "submitted_at": None, "result": None, "error": None,
               "_seq": uuid.uuid4().time}
        _jobs[job_id] = job
    background.add_task(_run_job, job_id, req.page_num, req.src_text, req.context)
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def job_status(
    job_id: str,
    x_asost_token: str | None = Header(default=None),
):
    role = _authorize(x_asost_token, READ_ROLES)
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"job غير موجود: {job_id}")
        response = {k: v for k, v in job.items() if not k.startswith("_")}
        # Observers can monitor operational state without receiving book text.
        if role == "observer":
            response.pop("result", None)
            response.pop("error", None)
        else:
            response["result"] = _redact_credentials(response.get("result"))
            if response.get("error"):
                response["error"] = "تعذر إكمال المهمة"
        return response


# ---------------------------------------------------------------- agents --
@router.get("/agents")
async def list_agents(x_asost_token: str | None = Header(default=None)):
    _authorize(x_asost_token, READ_ROLES)
    agents = []
    for d in sorted(AGENTS_DIR.iterdir()):
        ident_path = d / "identity.yaml"
        if not ident_path.is_file():
            continue
        try:
            import yaml
            ident = yaml.safe_load(ident_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            ident = {"error": str(exc)}
        agents.append({"dir": d.name,
                       "name": ident.get("name"),
                       "name_en": ident.get("name_en"),
                       "role": ident.get("role"),
                       "platform": ident.get("platform"),
                       "description": ident.get("description"),
                       "toolsets": ident.get("toolsets")})
    return {"count": len(agents), "agents": agents}


# ---------------------------------------------------------------- memory --
def _collection_count(data: object, names: frozenset[str]) -> int:
    """Count named collections by structure, never by returning their values."""
    if isinstance(data, dict):
        count = 0
        for key, value in data.items():
            if str(key).lower() in names:
                if isinstance(value, (dict, list)):
                    count += len(value)
                elif value is not None:
                    count += 1
            count += _collection_count(value, names)
        return count
    if isinstance(data, list):
        return sum(_collection_count(item, names) for item in data)
    return 0


def _memory_summary(data: object) -> dict[str, int]:
    return {
        "books": _collection_count(data, frozenset({"books", "book"})),
        "chapters": _collection_count(data, frozenset({"chapters", "chapter"})),
        "terms": _collection_count(
            data, frozenset({"terms", "term", "glossary", "terminology"})
        ),
    }


@router.get("/memory")
async def memory(x_asost_token: str | None = Header(default=None)):
    _authorize(x_asost_token, READ_ROLES)
    if not MEMORY_PATH.is_file():
        return {"exists": False, "summary": {"books": 0, "chapters": 0, "terms": 0}}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(500, "تعذر قراءة ملخص الذاكرة") from exc
    return {"exists": True, "summary": _memory_summary(data)}
