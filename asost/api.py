"""FastAPI router exposing the ASOST agents through durable jobs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ASOST_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ASOST_DIR / "agents"
MEMORY_PATH = Path("/opt/data/projects/assost/asost_memory.json")
JOBS_DB_PATH = Path(os.environ.get("ASOST_JOBS_DB", ASOST_DIR / "jobs.db"))

MAX_SRC_TEXT_CHARS = 20000
MAX_JOBS = int(os.environ.get("ASOST_MAX_JOBS", "50"))
TERMINAL_STATUSES = frozenset({"DONE", "ERROR", "CANCELLED"})

router = APIRouter(prefix="/api/asost", tags=["asost"])
_cancel_events: dict[str, threading.Event] = {}
_events_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    """SQLite job store using the Book Supervisor job-envelope fields."""

    fields = (
        "job_id", "owner_id", "book_id", "run_id", "status", "created_at",
        "started_at", "finished_at", "checkpoint", "error_code",
    )

    def __init__(self, path: Path = JOBS_DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asost_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    book_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    checkpoint TEXT,
                    error_code TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_asost_jobs_owner_created "
                "ON asost_jobs(owner_id, created_at DESC)"
            )
            # A process which disappeared cannot still own RUNNING work.
            conn.execute(
                "UPDATE asost_jobs SET status='INTERRUPTED', "
                "finished_at=NULL, error_code='SERVER_RESTART' WHERE status='RUNNING'"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        job = dict(row)
        try:
            job["checkpoint"] = json.loads(job["checkpoint"] or "null")
        except (TypeError, ValueError):
            job["checkpoint"] = None
        return job

    def create(self, *, owner_id: str, book_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
        job_id, run_id, created_at = uuid.uuid4().hex, uuid.uuid4().hex, _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO asost_jobs VALUES (?, ?, ?, ?, 'QUEUED', ?, NULL, NULL, ?, NULL)",
                (job_id, owner_id, book_id, run_id, created_at,
                 json.dumps(checkpoint, ensure_ascii=False)),
            )
            self._apply_retention(conn)
        return self.get(job_id)  # type: ignore[return-value]

    def _apply_retention(self, conn: sqlite3.Connection) -> None:
        """Remove only oldest terminal rows; active work never pays the display cap."""
        excess = conn.execute("SELECT MAX(COUNT(*) - ?, 0) FROM asost_jobs", (MAX_JOBS,)).fetchone()[0]
        if excess:
            conn.execute(
                "DELETE FROM asost_jobs WHERE job_id IN ("
                "SELECT job_id FROM asost_jobs WHERE status IN ('DONE','ERROR','CANCELLED') "
                "ORDER BY COALESCE(finished_at, created_at), created_at LIMIT ?)",
                (excess,),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            return self._decode(conn.execute(
                "SELECT * FROM asost_jobs WHERE job_id=?", (job_id,)
            ).fetchone())

    def update(self, job_id: str, **values: Any) -> None:
        if not values or not set(values).issubset(self.fields):
            raise ValueError("invalid job update")
        if "checkpoint" in values:
            values["checkpoint"] = json.dumps(values["checkpoint"], ensure_ascii=False)
        columns = ", ".join(f"{key}=?" for key in values)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE asost_jobs SET {columns} WHERE job_id=?", (*values.values(), job_id))

    def claim(self, job_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE asost_jobs SET status='RUNNING', started_at=?, finished_at=NULL, "
                "error_code=NULL WHERE job_id=? AND status IN ('QUEUED','INTERRUPTED')",
                (_now(), job_id),
            )
            return cur.rowcount == 1


STORE = JobRepository()


def _authenticate(token: str | None, owner_header: str | None) -> str:
    """Authenticate the caller and return its stable, persisted owner identity."""
    expected = os.environ.get("ASOST_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "الكتابة معطلة: ASOST_API_TOKEN غير مضبوط على الخادم")
    if not token or token != expected:
        raise HTTPException(401, "توكن مفقود أو غير صحيح (header X-ASOST-Token)")
    # Deployments with an authenticating proxy should forward its subject. The
    # token fingerprint preserves compatibility for single-owner deployments.
    return owner_header or hashlib.sha256(token.encode()).hexdigest()[:32]


def _owned_job(job_id: str, owner_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    # Deliberately hide whether another owner's identifier exists.
    if not job or job["owner_id"] != owner_id:
        raise HTTPException(404, f"job غير موجود: {job_id}")
    return job


def _get_orchestrator():
    try:
        from .orchestrator import ASOSTOrchestrator
    except ImportError:  # Supports running api.py with asost/ on sys.path.
        from orchestrator import ASOSTOrchestrator
    return ASOSTOrchestrator()


class TranslateRequest(BaseModel):
    page_num: int
    src_text: str
    context: str = ""
    book_id: str | None = None


def _run_job(job_id: str) -> None:
    if not STORE.claim(job_id):
        return
    job = STORE.get(job_id)
    if not job:
        return
    checkpoint = job["checkpoint"] or {}
    with _events_lock:
        cancel_event = _cancel_events.setdefault(job_id, threading.Event())
    try:
        result = _get_orchestrator().translate_page(
            checkpoint["page_num"], checkpoint["src_text"], checkpoint.get("context", "")
        )
        if cancel_event.is_set():
            STORE.update(job_id, status="CANCELLED", finished_at=_now(), error_code="CANCELLED_BY_OWNER")
        else:
            checkpoint["result"] = result
            checkpoint["resume_from"] = "complete"
            STORE.update(job_id, status="DONE", finished_at=_now(), checkpoint=checkpoint)
    except Exception as exc:  # noqa: BLE001
        checkpoint["error_message"] = str(exc)[:1000]
        STORE.update(job_id, status="ERROR", finished_at=_now(), checkpoint=checkpoint,
                     error_code=exc.__class__.__name__.upper())
    finally:
        with _events_lock:
            _cancel_events.pop(job_id, None)


@router.post("/translate-page")
async def translate_page(req: TranslateRequest, background: BackgroundTasks,
                         x_asost_token: str | None = Header(default=None),
                         x_owner_id: str | None = Header(default=None)):
    owner_id = _authenticate(x_asost_token, x_owner_id)
    if req.page_num < 1:
        raise HTTPException(422, f"page_num غير صالح: {req.page_num}")
    if len(req.src_text) > MAX_SRC_TEXT_CHARS:
        raise HTTPException(422, f"src_text أكبر من الحد ({len(req.src_text)} > {MAX_SRC_TEXT_CHARS} حرفاً)")
    job = STORE.create(
        owner_id=owner_id,
        book_id=req.book_id or f"page-{req.page_num}",
        checkpoint={"resume_from": "translate", "page_num": req.page_num,
                    "src_text": req.src_text, "context": req.context},
    )
    background.add_task(_run_job, job["job_id"])
    return {"job_id": job["job_id"], "run_id": job["run_id"], "status": job["status"]}


@router.get("/status/{job_id}")
async def job_status(job_id: str, x_asost_token: str | None = Header(default=None),
                     x_owner_id: str | None = Header(default=None)):
    return _owned_job(job_id, _authenticate(x_asost_token, x_owner_id))


@router.post("/cancel/{job_id}")
async def cancel_job(job_id: str, x_asost_token: str | None = Header(default=None),
                     x_owner_id: str | None = Header(default=None)):
    job = _owned_job(job_id, _authenticate(x_asost_token, x_owner_id))
    if job["status"] in TERMINAL_STATUSES:
        return job
    with _events_lock:
        event = _cancel_events.setdefault(job_id, threading.Event())
        event.set()
    STORE.update(job_id, status="CANCELLED", finished_at=_now(), error_code="CANCELLED_BY_OWNER")
    return STORE.get(job_id)


@router.post("/resume/{job_id}")
async def resume_job(job_id: str, background: BackgroundTasks,
                     x_asost_token: str | None = Header(default=None),
                     x_owner_id: str | None = Header(default=None)):
    job = _owned_job(job_id, _authenticate(x_asost_token, x_owner_id))
    if job["status"] != "INTERRUPTED":
        raise HTTPException(409, "يمكن استئناف مهمة INTERRUPTED فقط")
    background.add_task(_run_job, job_id)
    return {"job_id": job_id, "status": "QUEUED_FOR_RESUME", "checkpoint": job["checkpoint"]}


@router.get("/download/{job_id}")
async def download_job(job_id: str, x_asost_token: str | None = Header(default=None),
                       x_owner_id: str | None = Header(default=None)):
    job = _owned_job(job_id, _authenticate(x_asost_token, x_owner_id))
    if job["status"] != "DONE" or not (job["checkpoint"] or {}).get("result"):
        raise HTTPException(404, "النتيجة غير متوفرة بعد")
    return JSONResponse(job["checkpoint"]["result"], headers={
        "Content-Disposition": f'attachment; filename="{job_id}.json"'
    })


@router.get("/agents")
async def list_agents():
    agents = []
    for directory in sorted(AGENTS_DIR.iterdir()):
        ident_path = directory / "identity.yaml"
        if not ident_path.is_file():
            continue
        try:
            import yaml
            ident = yaml.safe_load(ident_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            ident = {"error": str(exc)}
        agents.append({"dir": directory.name, **{
            key: ident.get(key) for key in
            ("name", "name_en", "role", "platform", "description", "toolsets")
        }})
    return {"count": len(agents), "agents": agents}


@router.get("/memory")
async def memory():
    if not MEMORY_PATH.is_file():
        return {"exists": False, "data": {}}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(500, f"ملف الذاكرة تالف: {exc}") from exc
    return {"exists": True, "path": str(MEMORY_PATH), "data": data}
