#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASOST Dashboard Server
=======================
طبقة ربط (Integration Layer) بين محرك الترجمة الأصلي (PF.py — غير مُعدَّل إطلاقاً)
وواجهة الداشبورد الأمامية (static/index.html + script.js).

هذا الملف لا يُغيّر أي سطر داخل PF.py ولا أي منطق ترجمة، ولا يلمس مصفوفة
مفاتيح الـ API (تبقى يدوية كما هي بالكود الأصلي تماماً). كل ما يفعله:

  1. يستورد PF.py كوحدة Python عادية (import PF) دون أي تعديل عليه.
  2. ينشئ نسخة واحدة من MasterTranslationSystem تُستخدم طوال عمر السيرفر.
  3. يلتقط سجلات (logs) PF.py الحقيقية عبر إضافة logging.Handler لنفس
     الـ loggers التي أنشأها PF.py بنفسه (لا تعديل، فقط "استماع إضافي").
  4. يدير طابور ملفات (queue) حقيقي يعالجها المحرك بالتتابع تماماً كما
     صُمم أصلاً (لا تعديل على منطق الترجمة التسلسلي).
  5. يعرض كل ذلك عبر REST API بسيط يستهلكه script.js في الواجهة.

التشغيل:
    pip install -r requirements.txt
    python server.py
    → افتح المتصفح على http://localhost:8000
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --------------------------------------------------------------------------
# استيراد محرك الترجمة الأصلي كما هو — بدون أي تعديل على PF.py
# --------------------------------------------------------------------------
import PF  # noqa: E402  (المحرك الأصلي، غير مُعدَّل)

try:
    import PyPDF2  # already a hard dependency of PF.py itself
except ImportError:  # pragma: no cover
    PyPDF2 = None


# ============================================================================
#  المسارات والإعدادات العامة
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
DASH_DB_PATH = BASE_DIR / "dashboard_jobs.db"

for _d in (UPLOAD_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# يمكن تخطي اختبار المفاتيح التلقائي عند الإقلاع عبر متغير بيئة (اختياري،
# مفيد فقط أثناء التطوير المحلي بلا اتصال إنترنت). الافتراضي: يعمل تماماً
# كسلوك PF.py الأصلي عند تشغيله من CLI بدون --skip-api-test.
SKIP_STARTUP_KEY_TEST = os.environ.get("ASOST_SKIP_KEY_TEST", "0") == "1"

APP_START_TIME = time.time()


# ============================================================================
#  1) التقاط السجلات الحقيقية من PF.py (logging bridge)
# ============================================================================
#
# PF.py يستخدم structlog فوق stdlib logging. عندما يُستدعى main_logger.info(),
# ينتهي الأمر بتمرير LogRecord إلى كل الـ handlers المُسجَّلة على
# logging.getLogger('main') / logging.getLogger('quality_control').
# نحن فقط نُضيف handler خاص بنا لنفس الـ loggers (دون حذف أو تعديل أي
# handler موجود أصلاً) لالتقاط كل سطر حقيقي يصدر فعلياً من محرك الترجمة.

_log_seq = 0
_log_buffer: deque = deque(maxlen=1000)


def _classify_level(levelname: str) -> str:
    lv = (levelname or "").upper()
    if lv in ("ERROR", "CRITICAL"):
        return "err"
    if lv == "WARNING":
        return "warn"
    return "sys"


class DashboardLogHandler(logging.Handler):
    """Handler إضافي (غير جراحي) يلتقط سجلات PF.py الحقيقية لعرضها حيّة."""

    def emit(self, record: logging.LogRecord) -> None:
        global _log_seq
        try:
            payload = record.msg if isinstance(record.msg, dict) else None
            message = str(payload.get("event")) if payload else record.getMessage()
            level = str(payload.get("level")).upper() if payload and payload.get("level") else record.levelname
            source = str(payload.get("logger")) if payload and payload.get("logger") else record.name
            ts = payload.get("timestamp") if payload else None
            if not ts:
                ts = datetime.now(timezone.utc).isoformat()
        except Exception:
            message = "<log formatting error>"
            level = "INFO"
            source = record.name
            ts = datetime.now(timezone.utc).isoformat()

        _log_seq += 1
        entry = {
            "seq": _log_seq,
            "ts": ts,
            "level": level,
            "type": _classify_level(level),
            "source": source,
            "message": message,
        }
        _log_buffer.append(entry)

        # نمرر كل سطر أيضاً لمتتبّع التقدّم (ProgressTracker) ليكتشف
        # انتقالات المراحل الحقيقية (Phase 1..5) وأحداث الفصول.
        try:
            PROGRESS.on_log_event(message)
        except Exception:
            pass


def emit_dashboard_log(message: str, level: str = "INFO") -> None:
    """يسمح لكود السيرفر نفسه بإضافة سطور حقيقية (رفع ملف، إلغاء مهمة...)."""
    global _log_seq
    _log_seq += 1
    _log_buffer.append({
        "seq": _log_seq,
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "type": _classify_level(level),
        "source": "dashboard",
        "message": message,
    })


def get_logs_since(after: int, limit: int = 300) -> Dict[str, Any]:
    logs = [e for e in _log_buffer if e["seq"] > after]
    if len(logs) > limit:
        logs = logs[-limit:]
    last_seq = _log_buffer[-1]["seq"] if _log_buffer else after
    return {"logs": logs, "last_seq": last_seq}


# تركيب الـ handler على نفس الـ loggers الحقيقيين اللذين أنشأهما PF.py
logging.getLogger("main").addHandler(DashboardLogHandler())
logging.getLogger("quality_control").addHandler(DashboardLogHandler())


# ============================================================================
#  2) نموذج المهمة (Job) وقاعدة بيانات لوحة التحكم الخاصة (منفصلة عن PF.py)
# ============================================================================
#
# قاعدة بيانات جديدة خاصة بطبقة الربط فقط (dashboard_jobs.db) — لا علاقة
# لها بقواعد بيانات PF.py الخاصة (master_translation_enhanced.db أو
# key_statistics.db) والتي تبقى كما هي بلا أي تدخل.

STAGE_LABELS = [
    "EXTRACT & ANALYZE",
    "TRANSLATE CHAPTERS",
    "QUALITY CHECK",
    "BUILD TOC",
    "ASSEMBLE DOCUMENT",
]
# الوزن النسبي التقريبي لكل مرحلة من إجمالي زمن المعالجة الحقيقي —
# مرحلة الترجمة (2) هي الأثقل فعلياً لأنها تحتوي كل طلبات Gemini.
STAGE_WEIGHTS = [5, 78, 3, 4, 10]


def _init_dash_db() -> None:
    with sqlite3.connect(DASH_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                saved_path TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                paused INTEGER NOT NULL DEFAULT 0,
                queue_pos INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                stage_index INTEGER NOT NULL DEFAULT -1,
                chapters_total INTEGER NOT NULL DEFAULT 0,
                chapters_done INTEGER NOT NULL DEFAULT 0,
                skipped_chapters INTEGER NOT NULL DEFAULT 0,
                words_total INTEGER NOT NULL DEFAULT 0,
                words_done INTEGER NOT NULL DEFAULT 0,
                pages_total INTEGER NOT NULL DEFAULT 0,
                quality_avg REAL NOT NULL DEFAULT 0,
                output_path TEXT,
                html_report_path TEXT,
                deterministic_pdf_path TEXT,
                error_message TEXT,
                book_title TEXT,
                author TEXT
            )
        """)
        # ترحيل القواعد القديمة: أضِف الأعمدة الجديدة إن لم تكن موجودة
        existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "deterministic_pdf_path" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN deterministic_pdf_path TEXT")
        conn.commit()


class Job:
    __slots__ = (
        "id", "filename", "saved_path", "output_dir", "status", "paused",
        "queue_pos", "created_at", "started_at", "finished_at", "stage_index",
        "chapters_total", "chapters_done", "skipped_chapters", "words_total",
        "words_done", "pages_total", "quality_avg", "output_path",
        "html_report_path", "deterministic_pdf_path", "error_message", "book_title", "author",
        # عناصر تشغيلية داخلية فقط، لا تُخزَّن في القاعدة:
        "_stats_baseline", "_extraction_confirmed",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        if self.paused is None:
            self.paused = False
        if self.stage_index is None:
            self.stage_index = -1
        for f in ("chapters_total", "chapters_done", "skipped_chapters",
                   "words_total", "words_done", "pages_total"):
            if getattr(self, f) is None:
                setattr(self, f, 0)
        if self.quality_avg is None:
            self.quality_avg = 0.0
        self._stats_baseline = None
        self._extraction_confirmed = False

    def stage_label(self) -> str:
        if self.status == "QUEUED":
            return "queued"
        if self.status == "DONE":
            return "done"
        if self.status == "ERROR":
            return "error"
        if self.status == "CANCELLED":
            return "cancelled"
        if 0 <= self.stage_index < len(STAGE_LABELS):
            return STAGE_LABELS[self.stage_index]
        return "starting"

    def overall_pct(self) -> float:
        if self.status == "DONE":
            return 100.0
        if self.status in ("ERROR", "CANCELLED"):
            return 0.0
        if self.stage_index < 0:
            return 0.0
        done_weight = sum(STAGE_WEIGHTS[: self.stage_index])
        cur_weight = STAGE_WEIGHTS[self.stage_index] if self.stage_index < len(STAGE_WEIGHTS) else 0
        if self.stage_index == 1 and self.chapters_total:
            stage_frac = min(1.0, self.chapters_done / max(1, self.chapters_total))
        elif self.stage_index == 0:
            stage_frac = 0.4  # مرحلة الاستخراج غير قابلة للقياس الدقيق لحظياً
        else:
            stage_frac = 0.5
        return round(min(100.0, done_weight + cur_weight * stage_frac), 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "paused": bool(self.paused),
            "stage_index": self.stage_index,
            "stage_label": self.stage_label(),
            "overall_pct": self.overall_pct(),
            "chapters_total": self.chapters_total,
            "chapters_done": self.chapters_done,
            "skipped_chapters": self.skipped_chapters,
            "words_total": self.words_total,
            "words_done": self.words_done,
            "pages_total": self.pages_total,
            "quality_avg": round(self.quality_avg or 0.0, 2),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "book_title": self.book_title,
            "author": self.author,
            "output_ready": bool(self.output_path and self.status == "DONE"),
            "report_ready": bool(self.html_report_path and self.status == "DONE"),
            "error_message": self.error_message,
        }


class JobStore:
    """يدير المهام في الذاكرة + يحفظها في dashboard_jobs.db للاستمرارية."""

    def __init__(self):
        _init_dash_db()
        self.jobs: Dict[int, Job] = {}
        self.queue_order: List[int] = []  # ids بترتيب الأولوية (QUEUED فقط)
        self._load_from_db()

    def _load_from_db(self):
        with sqlite3.connect(DASH_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM jobs ORDER BY id ASC").fetchall()
        for r in rows:
            d = dict(r)
            # أي مهمة كانت "RUNNING" عند إيقاف السيرفر سابقاً تُعتبر متوقفة فعلياً
            if d["status"] == "RUNNING":
                d["status"] = "ERROR"
                d["error_message"] = "تمّ إيقاف السيرفر أثناء المعالجة (interrupted by restart)"
            job = Job(**d)
            self.jobs[job.id] = job
            if job.status == "QUEUED":
                self.queue_order.append(job.id)
        self.queue_order.sort(key=lambda jid: self.jobs[jid].queue_pos)

    def persist(self, job: Job):
        with sqlite3.connect(DASH_DB_PATH) as conn:
            conn.execute("""
                UPDATE jobs SET status=?, paused=?, queue_pos=?, started_at=?,
                    finished_at=?, stage_index=?, chapters_total=?, chapters_done=?,
                    skipped_chapters=?, words_total=?, words_done=?, pages_total=?,
                    quality_avg=?, output_path=?, html_report_path=?, deterministic_pdf_path=?, error_message=?,
                    book_title=?, author=?
                WHERE id=?
            """, (
                job.status, int(job.paused), job.queue_pos, job.started_at,
                job.finished_at, job.stage_index, job.chapters_total, job.chapters_done,
                job.skipped_chapters, job.words_total, job.words_done, job.pages_total,
                job.quality_avg, job.output_path, job.html_report_path, job.deterministic_pdf_path, job.error_message,
                job.book_title, job.author, job.id,
            ))
            conn.commit()

    def create(self, filename: str, saved_path: str, output_dir: str, pages_total: int) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(DASH_DB_PATH) as conn:
            cur = conn.execute("""
                INSERT INTO jobs (filename, saved_path, output_dir, status, paused,
                    queue_pos, created_at, stage_index, pages_total)
                VALUES (?, ?, ?, 'QUEUED', 0, ?, ?, -1, ?)
            """, (filename, saved_path, output_dir, len(self.queue_order), now, pages_total))
            conn.commit()
            job_id = cur.lastrowid
        job = Job(id=job_id, filename=filename, saved_path=saved_path, output_dir=output_dir,
                   status="QUEUED", paused=False, queue_pos=len(self.queue_order),
                   created_at=now, started_at=None, finished_at=None, stage_index=-1,
                   pages_total=pages_total)
        self.jobs[job_id] = job
        self.queue_order.append(job_id)
        return job

    def next_runnable(self) -> Optional[Job]:
        for jid in self.queue_order:
            job = self.jobs.get(jid)
            if job and job.status == "QUEUED" and not job.paused:
                return job
        return None

    def remove_from_queue(self, job_id: int):
        if job_id in self.queue_order:
            self.queue_order.remove(job_id)

    def all_sorted(self) -> List[Job]:
        """للعرض: قيد التشغيل أولاً، ثم قائمة الانتظار بترتيبها، ثم المكتملة/الأخطاء الأحدث أولاً."""
        running = [j for j in self.jobs.values() if j.status == "RUNNING"]
        queued = [self.jobs[jid] for jid in self.queue_order if jid in self.jobs]
        rest = [j for j in self.jobs.values() if j.status not in ("RUNNING", "QUEUED")]
        rest.sort(key=lambda j: j.id, reverse=True)
        return running + queued + rest[:25]  # نحدّ من السجل التاريخي المعروض


STORE = JobStore()


# ============================================================================
#  3) متتبّع التقدّم الحقيقي (Progress Tracker)
# ============================================================================
#
# يعتمد أساساً على قراءة system.translation_stats مباشرة (بيانات حيّة
# حقيقية من المحرك نفسه) وليس على تحليل نصوص السجلات. السجلات تُستخدم
# فقط لاكتشاف "متى تبدأ/تنتهي كل مرحلة" (Phase 1..5) عبر عبارات ثابتة
# موجودة فعلياً في الكود الأصلي دون أي محاولة لتخمين معلومات غير موجودة.

_PHASE_ANCHORS = [
    (0, "Phase 1: Extracting and analyzing the document"),
    (1, "Phase 2: Starting sequential translation"),
    (2, "Phase 3: Final Quality Check"),
    (3, "Phase 4: Creating organized table of contents"),
    (4, "Phase 5: Generating final novel document"),
]

_CHAPTER_START_RE = re.compile(r"Translating chapter (\d+)/(\d+): (.+)$")
_CHAPTER_SKIP_RE = re.compile(r"Skipping chapter (\d+)/(\d+): '(.*?)' \(previously")


class ProgressTracker:
    """يربط أسطر السجل الحيّة بحالة المهمة قيد التشغيل حالياً."""

    def __init__(self):
        self.current_job: Optional[Job] = None
        self.chapter_timeline: List[Dict[str, Any]] = []

    def start_job(self, job: Job):
        self.current_job = job
        self.chapter_timeline = []
        job.stage_index = 0
        job._extraction_confirmed = False

    def stop_job(self):
        self.current_job = None

    def on_log_event(self, message: str):
        job = self.current_job
        if job is None:
            return

        for stage_idx, anchor in _PHASE_ANCHORS:
            if anchor in message:
                job.stage_index = stage_idx
                if stage_idx == 1 and not job._extraction_confirmed:
                    # الاستخراج انتهى فعلياً الآن — نقرأ العدد الحقيقي المُحدَّث
                    job._extraction_confirmed = True
                break

        m = _CHAPTER_START_RE.search(message)
        if m:
            idx, total, title = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            self._record_chapter_event(idx, total, title, cached=False)
            return

        m = _CHAPTER_SKIP_RE.search(message)
        if m:
            idx, total, title = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            self._record_chapter_event(idx, total, title, cached=True)
            return

    def _record_chapter_event(self, idx: int, total: int, title: str, cached: bool):
        now = datetime.now(timezone.utc).isoformat()
        # اغلق الفصل السابق زمنياً عند بدء فصل جديد
        if self.chapter_timeline:
            prev = self.chapter_timeline[-1]
            if prev.get("end_ts") is None:
                prev["end_ts"] = now
        self.chapter_timeline.append({
            "index": idx, "total": total, "title": title[:80],
            "start_ts": now, "end_ts": now if cached else None,
            "cached": cached,
        })
        if len(self.chapter_timeline) > 60:
            self.chapter_timeline = self.chapter_timeline[-60:]

    def sync_numeric_progress(self, system: "PF.MasterTranslationSystem"):
        """يُستدعى بشكل متزامن (سريع، بلا await) عند كل استعلام حالة."""
        job = self.current_job
        if job is None or job._stats_baseline is None:
            return
        stats = system.translation_stats
        b = job._stats_baseline
        job.chapters_done = max(0, stats.get("completed_chapters", 0) - b["completed_chapters"])
        job.words_done = max(0, stats.get("translated_words", 0) - b["translated_words"])
        job.skipped_chapters = max(0, stats.get("skipped_chapters", 0) - b["skipped_chapters"])
        if job.stage_index >= 1:
            job.chapters_total = stats.get("total_chapters", job.chapters_total) or job.chapters_total
            job.words_total = stats.get("total_words", job.words_total) or job.words_total
        qcount = len(stats.get("quality_scores", [])) - b["quality_scores_len"]
        qsum = sum(stats.get("quality_scores", [])) - b["quality_scores_sum"]
        if qcount > 0:
            job.quality_avg = qsum / qcount


PROGRESS = ProgressTracker()


def snapshot_stats_baseline(system: "PF.MasterTranslationSystem") -> Dict[str, Any]:
    st = system.translation_stats
    return {
        "completed_chapters": st.get("completed_chapters", 0),
        "translated_words": st.get("translated_words", 0),
        "skipped_chapters": st.get("skipped_chapters", 0),
        "quality_scores_len": len(st.get("quality_scores", [])),
        "quality_scores_sum": sum(st.get("quality_scores", [])),
    }


# ============================================================================
#  4) طبقة مفاتيح الـ API — للقراءة فقط (لا إضافة / لا حذف / لا تدوير من الواجهة)
# ============================================================================
#
# تماماً كما طُلب: نظام المفاتيح يبقى يدوياً بالكامل داخل PF.py (المصفوفة
# المكتوبة يدوياً في EnhancedGeminiAPI.__init__). الداشبورد هنا للعرض فقط.

_tested_valid: Dict[str, Optional[bool]] = {}


def mask_key(key: str) -> str:
    if len(key) > 12:
        return f"{key[:8]}...{key[-4:]}"
    return key


def build_keys_table(system: "PF.MasterTranslationSystem") -> List[Dict[str, Any]]:
    out = []
    now = time.time()
    for i, key in enumerate(system.api_manager.api_keys, start=1):
        stats: PF.KeyStatistics = system.api_manager.key_stats[key]
        limiter: PF.TokenRateLimiter = system.api_manager.rate_limiters[key]
        rl_status = limiter.get_status()
        blocked_until = system.api_manager.blocked_keys.get(key)
        is_blocked = bool(blocked_until and blocked_until > now)
        tested = _tested_valid.get(key)

        if is_blocked:
            status = "BLOCKED"
        elif tested is False:
            status = "INVALID"
        elif rl_status["current_tpm_usage"] / max(1, rl_status["max_tpm"]) > 0.85:
            status = "COOLING"
        elif tested is True or stats.total_requests > 0:
            status = "ACTIVE"
        else:
            status = "UNKNOWN"

        out.append({
            "index": i,
            "alias": f"KEY-{i:02d}",
            "masked": mask_key(key),
            "status": status,
            "blocked": is_blocked,
            "blocked_for_seconds": max(0, int(blocked_until - now)) if is_blocked else 0,
            "tested_valid": tested,
            "health_score": round(stats.get_health_score(), 1),
            "success_rate": round(stats.get_success_rate(), 1),
            "total_requests": stats.total_requests,
            "successful_requests": stats.successful_requests,
            "failed_requests": stats.failed_requests,
            "tpm_current": rl_status["current_tpm_usage"],
            "tpm_limit": rl_status["max_tpm"],
            "rpm_current": rl_status["current_rpm_usage"],
            "rpm_limit": rl_status["effective_rpm"],
            "rpd_current": rl_status["current_rpd_usage"],
            "rpd_limit": rl_status["max_rpd"],
            "avg_response_time": round(stats.average_response_time, 2),
            "last_success": stats.last_success_time.isoformat() if stats.last_success_time else None,
            "last_error": stats.last_error_time.isoformat() if stats.last_error_time else None,
        })
    return out


async def run_startup_key_test(system: "PF.MasterTranslationSystem"):
    if SKIP_STARTUP_KEY_TEST:
        emit_dashboard_log(
            "تخطي اختبار المفاتيح عند الإقلاع (ASOST_SKIP_KEY_TEST=1)", "WARNING"
        )
        return
    try:
        results = await system.test_all_api_keys()
        _tested_valid.update(results)
    except RuntimeError as e:
        emit_dashboard_log(f"فشل اختبار المفاتيح عند الإقلاع: {e}", "ERROR")
    except Exception as e:  # لا نُسقط السيرفر مهما حدث أثناء الاختبار الاختياري
        emit_dashboard_log(f"تعذّر اختبار المفاتيح عند الإقلاع (شبكة/اتصال): {e}", "WARNING")


# ============================================================================
#  5) TPM history (نافذة متحركة حقيقية لاستهلاك كل مفتاح)
# ============================================================================

_tpm_history: deque = deque(maxlen=40)


def sample_tpm(system: "PF.MasterTranslationSystem"):
    per_key = {}
    for key in system.api_manager.api_keys:
        limiter = system.api_manager.rate_limiters[key]
        per_key[key] = limiter.get_status()["current_tpm_usage"]
    _tpm_history.append({"t": datetime.now(timezone.utc).isoformat(), "per_key": per_key})


def build_tpm_history_payload(system: "PF.MasterTranslationSystem") -> Dict[str, Any]:
    first_key = system.api_manager.api_keys[0] if system.api_manager.api_keys else None
    tpm_limit = (
        system.api_manager.rate_limiters[first_key].get_status()["max_tpm"]
        if first_key else 32000
    )
    if not _tpm_history:
        return {"labels": [], "series": [], "tpm_limit": tpm_limit}
    totals: Dict[str, int] = {}
    for snap in _tpm_history:
        for k, v in snap["per_key"].items():
            totals[k] = totals.get(k, 0) + v
    top_keys = sorted(totals, key=lambda k: totals[k], reverse=True)[:3]
    if not any(totals.values()):
        # لا يوجد أي استهلاك بعد — نعرض أول 3 مفاتيح فقط كخط أساس صفري حقيقي
        top_keys = system.api_manager.api_keys[:3]

    labels = []
    for snap in _tpm_history:
        try:
            dt = datetime.fromisoformat(snap["t"])
            labels.append(dt.strftime("%M:%S"))
        except Exception:
            labels.append("")

    key_to_index = {k: i for i, k in enumerate(system.api_manager.api_keys, start=1)}
    series = []
    for k in top_keys:
        series.append({
            "alias": f"KEY-{key_to_index.get(k, 0):02d}",
            "masked": mask_key(k),
            "data": [snap["per_key"].get(k, 0) for snap in _tpm_history],
        })
    return {"labels": labels, "series": series, "tpm_limit": tpm_limit}


# ============================================================================
#  6) إحصائيات تاريخية (heatmap + إجماليات) من dashboard_jobs.db
# ============================================================================

def compute_totals() -> Dict[str, int]:
    with sqlite3.connect(DASH_DB_PATH) as conn:
        row = conn.execute("""
            SELECT COUNT(*), COALESCE(SUM(words_done),0), COALESCE(SUM(pages_total),0),
                   COALESCE(SUM(chapters_done),0)
            FROM jobs WHERE status='DONE'
        """).fetchone()
    return {
        "books_completed": row[0] or 0,
        "words_translated": row[1] or 0,
        "pages_processed": row[2] or 0,
        "chapters_translated": row[3] or 0,
    }


def compute_heatmap(weeks: int = 12) -> List[Dict[str, Any]]:
    with sqlite3.connect(DASH_DB_PATH) as conn:
        rows = conn.execute("""
            SELECT date(finished_at) as d, COALESCE(SUM(pages_total),0)
            FROM jobs WHERE status='DONE' AND finished_at IS NOT NULL
            GROUP BY date(finished_at)
        """).fetchall()
    by_date = {r[0]: r[1] for r in rows}
    out = []
    today = datetime.now(timezone.utc).date()
    for i in range(weeks * 7 - 1, -1, -1):
        d = today.fromordinal(today.toordinal() - i)
        key = d.isoformat()
        out.append({"date": key, "pages": by_date.get(key, 0)})
    return out


def compute_radar(system: "PF.MasterTranslationSystem") -> Dict[str, float]:
    totals = compute_totals()
    # إن كانت هناك مهمة قيد التشغيل نستخدم بياناتها الحيّة، وإلا نعتمد
    # على المتوسطات التاريخية المخزّنة لكل المفاتيح.
    job = PROGRESS.current_job
    chapters_total = job.chapters_total if job else 0
    chapters_done = job.chapters_done if job else 0
    skipped = job.skipped_chapters if job else 0
    quality = job.quality_avg if job and job.quality_avg else 0.0

    with sqlite3.connect(DASH_DB_PATH) as conn:
        row = conn.execute("""
            SELECT COALESCE(AVG(quality_avg),0), COALESCE(SUM(chapters_done),0),
                   COALESCE(SUM(skipped_chapters),0)
            FROM jobs WHERE status='DONE'
        """).fetchone()
    hist_quality, hist_done, hist_skipped = row

    success_rate = 100.0 if totals["books_completed"] > 0 else (
        (chapters_done / chapters_total * 100) if chapters_total else 0.0
    )
    quality_val = quality if quality else (hist_quality or 0.0)
    cache_hit = (skipped / chapters_total * 100) if chapters_total else (
        (hist_skipped / hist_done * 100) if hist_done else 0.0
    )

    keys = system.api_manager.api_keys
    health_scores = [system.api_manager.key_stats[k].get_health_score() for k in keys]
    key_health = sum(health_scores) / len(health_scores) if health_scores else 0.0

    reliability = key_health  # نفس القياس المبني على معدلات فشل حقيقية للمفاتيح

    speed = 0.0
    if job and job.started_at and job.words_done:
        try:
            started = datetime.fromisoformat(job.started_at)
            elapsed_min = max(0.01, (datetime.now(timezone.utc) - started).total_seconds() / 60)
            wpm = job.words_done / elapsed_min
            speed = min(100.0, (wpm / 400.0) * 100.0)  # 400 wpm ≈ مرجع تطبيع بصري فقط
        except Exception:
            speed = 0.0

    return {
        "success_rate": round(success_rate, 1),
        "quality": round(quality_val * 10, 1),
        "key_health": round(key_health, 1),
        "cache_hit": round(cache_hit, 1),
        "reliability": round(reliability, 1),
        "speed": round(speed, 1),
    }


# ============================================================================
#  7) العامل الخلفي (Background Worker) — يعالج الطابور بالتتابع
# ============================================================================
#
# يستدعي PF.MasterTranslationSystem.process_complete_book كما هي تماماً —
# نفس الدالة العامة التي يستدعيها main() في PF.py الأصلي، بلا أي تعديل.

SYSTEM: Optional["PF.MasterTranslationSystem"] = None
_current_task: Optional[asyncio.Task] = None
_worker_task: Optional[asyncio.Task] = None
_queue_wakeup = asyncio.Event()


async def _run_single_job(job: Job):
    global _current_task
    assert SYSTEM is not None

    job.status = "RUNNING"
    job.started_at = datetime.now(timezone.utc).isoformat()
    STORE.remove_from_queue(job.id)
    STORE.persist(job)

    job._stats_baseline = snapshot_stats_baseline(SYSTEM)
    PROGRESS.start_job(job)

    emit_dashboard_log(f'بدء معالجة: "{job.filename}" (job #{job.id:04d})', "INFO")

    task = asyncio.ensure_future(
        SYSTEM.process_complete_book(job.saved_path, job.output_dir)
    )
    _current_task = task
    try:
        output_path = await task
        job.output_path = output_path

        # ── المؤلّف الحتمي: PDF مطابق للأصل (صور بمواضعها وأحجامها) ──
        try:
            from deterministic_composer import build_pages_flow
            from deterministic_render import render_pdf
            import json as _json
            _cache = Path(job.output_dir) / "paged_translations.json"
            if _cache.exists():
                _tr = _json.load(open(_cache))
                _pf, _rep = build_pages_flow(job.saved_path,
                                             str(Path(job.output_dir) / "images"), _tr)
                if _rep.get("pages"):
                    _pdf_out = str(Path(job.output_dir) / f"{Path(job.saved_path).stem}_حتمي.pdf")
                    render_pdf(_pf, _pdf_out, Path(job.filename).stem)
                    job.deterministic_pdf_path = _pdf_out
                    emit_dashboard_log(
                        f'المؤلف الحتمي: {_rep["pages"]} صفحة، '
                        f'{_rep["illustration_pages"]} رسمة كاملة — {_pdf_out}', "INFO"
                    )
        except Exception as _det_exc:
            emit_dashboard_log(f'المؤلف الحتمي تخطّى (غير حرج): {_det_exc}', "WARNING")

        job.stage_index = 5
        job.status = "DONE"
        # نبحث عن تقرير الـ HTML المولَّد فعلياً داخل مجلد الإخراج (بدون
        # تخمين الاسم — نعتمد على ما أنتجه المحرك فعلياً على القرص)
        reports = sorted(glob.glob(str(Path(job.output_dir) / "translation_report_*.html")))
        if reports:
            job.html_report_path = reports[-1]
        PROGRESS.sync_numeric_progress(SYSTEM)
        emit_dashboard_log(
            f'اكتملت الترجمة بنجاح: "{job.filename}" — {job.chapters_done} فصل', "INFO"
        )
    except asyncio.CancelledError:
        job.status = "CANCELLED"
        job.error_message = "أُلغيت المهمة من الواجهة"
        emit_dashboard_log(f'أُلغيت المهمة: "{job.filename}"', "WARNING")
    except Exception as e:
        job.status = "ERROR"
        job.error_message = str(e)[:500]
        emit_dashboard_log(f'فشلت المهمة: "{job.filename}" — {e}', "ERROR")
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
        _current_task = None
        PROGRESS.stop_job()
        STORE.persist(job)


async def _worker_loop():
    while True:
        job = STORE.next_runnable()
        if job is None:
            _queue_wakeup.clear()
            try:
                await asyncio.wait_for(_queue_wakeup.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            continue
        await _run_single_job(job)


async def _tpm_sampler_loop():
    while True:
        try:
            if SYSTEM is not None:
                sample_tpm(SYSTEM)
                if PROGRESS.current_job is not None:
                    PROGRESS.sync_numeric_progress(SYSTEM)
                    STORE.persist(PROGRESS.current_job)  # صمود أمام انقطاع مفاجئ
        except Exception:
            pass
        await asyncio.sleep(3.5)


# ============================================================================
#  8) FastAPI application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global SYSTEM, _worker_task
    emit_dashboard_log("ASOST Dashboard Server starting up...", "INFO")
    SYSTEM = PF.MasterTranslationSystem(api_keys=[])  # لا مفاتيح إضافية — المصفوفة اليدوية فقط
    psutil.cpu_percent(interval=None)  # تهيئة القراءة الأولى لـ psutil
    asyncio.create_task(run_startup_key_test(SYSTEM))
    _worker_task = asyncio.create_task(_worker_loop())
    asyncio.create_task(_tpm_sampler_loop())
    emit_dashboard_log(
        f"النظام جاهز — {len(SYSTEM.api_manager.api_keys)} مفتاح API محمَّل يدوياً من الكود الأصلي",
        "INFO",
    )
    yield
    emit_dashboard_log("ASOST Dashboard Server shutting down...", "WARNING")
    if _current_task:
        _current_task.cancel()
    if _worker_task:
        _worker_task.cancel()
    try:
        await SYSTEM.api_manager.cleanup()
    except Exception:
        pass


app = FastAPI(title="ASOST Dashboard", lifespan=lifespan)

# --- ASOST-agents router (ترجمة عبر الوكلاء) ---
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from asost.api import router as asost_router  # noqa: E402
app.include_router(asost_router)



# ---------------------------------------------------------------- /api/state

@app.get("/api/state")
async def api_state():
    assert SYSTEM is not None
    PROGRESS.sync_numeric_progress(SYSTEM)

    cpu = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()

    keys = SYSTEM.api_manager.api_keys
    now = time.time()
    active = cooling = blocked = invalid = 0
    for k in keys:
        if k in SYSTEM.api_manager.blocked_keys and SYSTEM.api_manager.blocked_keys[k] > now:
            blocked += 1
        elif _tested_valid.get(k) is False:
            invalid += 1
        else:
            limiter_status = SYSTEM.api_manager.rate_limiters[k].get_status()
            if limiter_status["current_tpm_usage"] / max(1, limiter_status["max_tpm"]) > 0.85:
                cooling += 1
            else:
                active += 1

    jobs = STORE.all_sorted()
    current_job = PROGRESS.current_job
    last_job = next((j for j in jobs if j.status in ("DONE", "ERROR")), None)

    return JSONResponse({
        "server_time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(time.time() - APP_START_TIME),
        "system": {
            "cpu_percent": round(cpu, 1),
            "ram_used_gb": round(vm.used / (1024 ** 3), 1),
            "ram_total_gb": round(vm.total / (1024 ** 3), 1),
            "ram_percent": round(vm.percent, 1),
        },
        "totals": compute_totals(),
        "keys_summary": {
            "total": len(keys), "active": active, "cooling": cooling,
            "blocked": blocked, "invalid": invalid,
            "tested": len(_tested_valid) > 0,
        },
        "queue": [j.to_dict() for j in jobs],
        "current_job_id": current_job.id if current_job else None,
        "chapter_timeline": PROGRESS.chapter_timeline[-14:],
        "tpm_history": build_tpm_history_payload(SYSTEM),
        "radar": compute_radar(SYSTEM),
        "heatmap": compute_heatmap(),
        "output_last_status": last_job.status if last_job else None,
    })


@app.get("/api/keys")
async def api_keys():
    assert SYSTEM is not None
    return JSONResponse({"keys": build_keys_table(SYSTEM)})


@app.get("/api/logs")
async def api_logs(after: int = 0, limit: int = 300):
    return JSONResponse(get_logs_since(after, limit))


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "engine_ready": SYSTEM is not None,
            "keys_loaded": len(SYSTEM.api_manager.api_keys) if SYSTEM else 0}


# --------------------------------------------------------------- /api/upload

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "لم يتم إرسال أي ملف")

    job_output_dir = OUTPUT_DIR / uuid.uuid4().hex[:12]
    safe_name = re.sub(r"[^\w.\-\u0600-\u06FF ]", "_", file.filename)[:150]
    saved_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:10]}_{safe_name}"

    content = await file.read()
    with open(saved_path, "wb") as f:
        f.write(content)

    # نستخدم دالة PF.py الأصلية نفسها للتحقق (validate_input_paths) —
    # بدون أي تعديل عليها — لضمان اتساق قواعد القبول مع محرك الترجمة تماماً.
    is_valid, message = PF.validate_input_paths(str(saved_path), str(job_output_dir))
    if not is_valid:
        try:
            saved_path.unlink(missing_ok=True)
        except Exception:
            pass
        emit_dashboard_log(f'رُفض الملف "{file.filename}": {message}', "WARNING")
        raise HTTPException(400, message)

    pages_total = 0
    if PyPDF2 is not None:
        try:
            reader = PyPDF2.PdfReader(str(saved_path))
            pages_total = len(reader.pages)
        except Exception:
            pages_total = 0

    job = STORE.create(file.filename, str(saved_path), str(job_output_dir), pages_total)
    emit_dashboard_log(
        f'استلام ملف جديد: "{file.filename}" ({pages_total} صفحة) → أُضيف للطابور (#{job.id:04d})',
        "INFO",
    )
    _queue_wakeup.set()
    return JSONResponse(job.to_dict(), status_code=201)


# --------------------------------------------------------- /api/queue/* actions

def _get_job_or_404(job_id: int) -> Job:
    job = STORE.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "المهمة غير موجودة")
    return job


@app.post("/api/queue/{job_id}/pause")
async def api_pause(job_id: int):
    job = _get_job_or_404(job_id)
    if job.status != "QUEUED":
        raise HTTPException(400, "لا يمكن إيقاف مهمة إلا وهي في طابور الانتظار")
    job.paused = True
    STORE.persist(job)
    emit_dashboard_log(f'أُوقفت مؤقتاً: "{job.filename}"', "INFO")
    return job.to_dict()


@app.post("/api/queue/{job_id}/resume")
async def api_resume(job_id: int):
    job = _get_job_or_404(job_id)
    job.paused = False
    STORE.persist(job)
    emit_dashboard_log(f'استؤنفت: "{job.filename}"', "INFO")
    _queue_wakeup.set()
    return job.to_dict()


@app.post("/api/queue/{job_id}/priority-up")
async def api_priority_up(job_id: int):
    job = _get_job_or_404(job_id)
    if job.status != "QUEUED":
        raise HTTPException(400, "الأولوية تنطبق فقط على مهام الانتظار")
    if job_id in STORE.queue_order:
        STORE.queue_order.remove(job_id)
        STORE.queue_order.insert(0, job_id)
        for pos, jid in enumerate(STORE.queue_order):
            STORE.jobs[jid].queue_pos = pos
            STORE.persist(STORE.jobs[jid])
    emit_dashboard_log(f'أولوية أعلى: "{job.filename}"', "INFO")
    return job.to_dict()


@app.delete("/api/queue/{job_id}")
async def api_remove(job_id: int):
    job = _get_job_or_404(job_id)
    if job.status == "RUNNING":
        if _current_task and PROGRESS.current_job and PROGRESS.current_job.id == job_id:
            _current_task.cancel()
            emit_dashboard_log(f'طلب إلغاء المهمة الجارية: "{job.filename}"', "WARNING")
        return job.to_dict()
    STORE.remove_from_queue(job_id)
    del STORE.jobs[job_id]
    with sqlite3.connect(DASH_DB_PATH) as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    emit_dashboard_log(f'أُزيلت من الطابور: "{job.filename}"', "INFO")
    return {"removed": True, "id": job_id}


@app.post("/api/queue/pause-all")
async def api_pause_all():
    n = 0
    for jid in STORE.queue_order:
        job = STORE.jobs[jid]
        if not job.paused:
            job.paused = True
            STORE.persist(job)
            n += 1
    emit_dashboard_log(f"إيقاف مؤقت لكل ملفات الانتظار ({n})", "INFO")
    return {"paused": n}


@app.post("/api/queue/resume-all")
async def api_resume_all():
    n = 0
    for jid in STORE.queue_order:
        job = STORE.jobs[jid]
        if job.paused:
            job.paused = False
            STORE.persist(job)
            n += 1
    emit_dashboard_log(f"استئناف كل ملفات الانتظار ({n})", "INFO")
    _queue_wakeup.set()
    return {"resumed": n}


# ------------------------------------------------------------- /api/download

@app.get("/api/download/{job_id}/docx")
async def api_download_docx(job_id: int):
    job = _get_job_or_404(job_id)
    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(404, "الملف النهائي غير متوفر بعد")
    return FileResponse(job.output_path, filename=Path(job.output_path).name)


@app.get("/api/download/{job_id}/report")
async def api_download_report(job_id: int):
    job = _get_job_or_404(job_id)
    if not job.html_report_path or not Path(job.html_report_path).exists():
        raise HTTPException(404, "التقرير غير متوفر بعد")
    return FileResponse(job.html_report_path, filename=Path(job.html_report_path).name)


# --------------------------------------------------------------- static files
# يجب تركيبها أخيراً حتى لا تحجب أي مسار من مسارات /api/* أعلاه.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    # منصات الاستضافة (Railway وغيرها) تحدد رقم المنفذ تلقائياً عبر متغير
    # البيئة PORT. محلياً، إن لم يوجد هذا المتغير، يبقى المنفذ 8000 كما كان.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
