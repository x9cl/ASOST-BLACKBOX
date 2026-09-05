"""api.py — FastAPI router لربط منظومة ASOST-agents بالداشبورد.

يُضاف إلى server.py بسطرين فقط:
    from asost.api import router as asost_router
    app.include_router(asost_router)

Endpoints:
    POST /api/asost/translate-page  {page_num, src_text, context} → {job_id}
    GET  /api/asost/status/{job_id} → حالة المهمة + النتيجة
    GET  /api/asost/agents          → الوكلاء المسجلون وهوياتهم
    GET  /api/asost/memory          → ملخص ذاكرة آمن ومصادق عليه
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

from .config import settings
from .store import ASOSTStore

ASOST_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ASOST_DIR / "agents"
MEMORY_PATH = settings.memory_path

MAX_SRC_TEXT_CHARS = 20000
MAX_JOBS = 50  # نحتفظ بآخر 50 مهمة فقط (تنظيف الأقدم عند الإضافة)

router = APIRouter(prefix="/api/asost", tags=["asost"])

_store_instance: ASOSTStore | None = None
_lock = threading.Lock()


def _store() -> ASOSTStore:
    global _store_instance
    with _lock:
        if _store_instance is None:
            _store_instance = ASOSTStore(settings.state_db_path)
        return _store_instance


def _check_auth(x_asost_token: str | None) -> str:
    """تحقق توكن الكتابة: ASOST_API_TOKEN من env عبر header X-ASOST-Token."""
    expected = os.environ.get("ASOST_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "الكتابة معطلة: ASOST_API_TOKEN غير مضبوط على الخادم")
    if not x_asost_token or not secrets.compare_digest(x_asost_token, expected):
        raise HTTPException(401, "توكن مفقود أو غير صحيح (header X-ASOST-Token)")
    return "operator"


def _get_orchestrator():
    from asost.orchestrator import ASOSTOrchestrator
    return ASOSTOrchestrator()


# ------------------------------------------------------------- translate --
class TranslateRequest(BaseModel):
    page_num: int
    src_text: str
    context: str = ""


def _run_job(job_id: str, page_num: int, src_text: str, context: str):
    _store().update_api_job(job_id, "running")
    try:
        orch = _get_orchestrator()
        result = orch.translate_page(page_num, src_text, context)
        _store().update_api_job(job_id, "done", result=result)
    except Exception as exc:  # noqa: BLE001
        _store().update_api_job(job_id, "error", error=str(exc)[:500])


@router.post("/translate-page")
async def translate_page(
    req: TranslateRequest,
    background: BackgroundTasks,
    x_asost_token: str | None = Header(default=None),
):
    owner_id = _check_auth(x_asost_token)
    if req.page_num < 1:
        raise HTTPException(422, f"page_num غير صالح: {req.page_num}")
    if len(req.src_text) > MAX_SRC_TEXT_CHARS:
        raise HTTPException(
            422, f"src_text أكبر من الحد ({len(req.src_text)} > "
                 f"{MAX_SRC_TEXT_CHARS} حرفاً)")
    job_id = uuid.uuid4().hex[:12]
    try:
        _store().create_api_job(
            job_id, owner_id,
            {"page_num": req.page_num, "context_supplied": bool(req.context)},
            MAX_JOBS,
        )
    except OverflowError as exc:
        raise HTTPException(429, str(exc)) from exc
    background.add_task(_run_job, job_id, req.page_num, req.src_text, req.context)
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def job_status(job_id: str, x_asost_token: str | None = Header(default=None)):
    owner_id = _check_auth(x_asost_token)
    job = _store().get_api_job(job_id, owner_id)
    if not job:
        raise HTTPException(404, f"job غير موجود: {job_id}")
    return {key: job[key] for key in (
        "job_id", "status", "result", "error", "created_at", "updated_at"
    )}


# ---------------------------------------------------------------- agents --
@router.get("/agents")
async def list_agents(x_asost_token: str | None = Header(default=None)):
    _check_auth(x_asost_token)
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
@router.get("/memory")
async def memory(book_id: str = "", x_asost_token: str | None = Header(default=None)):
    _check_auth(x_asost_token)
    if book_id:
        return {"exists": True, "book_id": book_id,
                "namespaces": _store().memory_summary(book_id)}
    if not MEMORY_PATH.is_file():
        return {"exists": False, "data": {}}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(500, f"ملف الذاكرة تالف: {exc}") from exc
    return {"exists": True, "keys": sorted(data), "entries": len(data)}
