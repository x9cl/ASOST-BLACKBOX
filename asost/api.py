"""api.py — FastAPI router لربط منظومة ASOST-agents بالداشبورد.

يُضاف إلى server.py بسطرين فقط:
    from asost.api import router as asost_router
    app.include_router(asost_router)

Endpoints:
    POST /api/asost/translate-page  {book_id, run_id, agent_instance_id,
                                     page_num, src_text, context} → {job_id}
    GET  /api/asost/status/{job_id} → حالة المهمة + النتيجة
    GET  /api/asost/agents          → الوكلاء الستة وهويتهم من identity.yaml
    GET  /api/asost/memory          → محتوى asost_memory.json
"""
from __future__ import annotations

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


def _check_write_auth(x_asost_token: str | None):
    """تحقق توكن الكتابة: ASOST_API_TOKEN من env عبر header X-ASOST-Token."""
    expected = os.environ.get("ASOST_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "الكتابة معطلة: ASOST_API_TOKEN غير مضبوط على الخادم")
    if not x_asost_token or x_asost_token != expected:
        raise HTTPException(401, "توكن مفقود أو غير صحيح (header X-ASOST-Token)")


def _get_orchestrator(book_id: str, run_id: str, agent_instance_id: str):
    from orchestrator import ASOSTOrchestrator
    return ASOSTOrchestrator(book_id, run_id, agent_instance_id)


# ------------------------------------------------------------- translate --
class TranslateRequest(BaseModel):
    book_id: str
    run_id: str
    agent_instance_id: str
    page_num: int
    src_text: str
    context: str = ""


def _run_job(job_id: str, book_id: str, run_id: str, agent_instance_id: str,
             page_num: int, src_text: str, context: str):
    with _lock:
        _jobs[job_id]["status"] = "running"
    try:
        orch = _get_orchestrator(book_id, run_id, agent_instance_id)
        result = orch.translate_page(page_num, src_text, context)
        with _lock:
            _jobs[job_id].update(status="done", result=result)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _jobs[job_id].update(status="error", error=str(exc))


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
        job = {"status": "queued", "book_id": req.book_id,
               "run_id": req.run_id,
               "agent_instance_id": req.agent_instance_id,
               "page_num": req.page_num,
               "submitted_at": None, "result": None, "error": None,
               "_seq": uuid.uuid4().time}
        _jobs[job_id] = job
    background.add_task(
        _run_job, job_id, req.book_id, req.run_id, req.agent_instance_id,
        req.page_num, req.src_text, req.context)
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def job_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"job غير موجود: {job_id}")
        return {k: v for k, v in job.items() if not k.startswith("_")}


# ---------------------------------------------------------------- agents --
@router.get("/agents")
async def list_agents():
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
async def memory():
    if not MEMORY_PATH.is_file():
        return {"exists": False, "data": {}}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(500, f"ملف الذاكرة تالف: {exc}") from exc
    return {"exists": True, "path": str(MEMORY_PATH), "data": data}
