"""Transactional SQLite state for ASOST books, runs, memory, and segments."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from asost.models import (
    RUN_TRANSITIONS, BookIdentity, RunIdentity, RunState, Segment, SegmentState,
)


SCHEMA_VERSION = 1


class ASOSTStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS books (
                    book_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL REFERENCES books(book_id),
                    owner_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    checkpoint TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS segments (
                    segment_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    chapter_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    source_hash TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    translation TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    score INTEGER,
                    revision INTEGER NOT NULL DEFAULT 0,
                    issues TEXT NOT NULL DEFAULT '[]',
                    provenance TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(run_id, chapter_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS memory (
                    book_id TEXT NOT NULL REFERENCES books(book_id),
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(book_id, namespace, key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported ASOST schema version: {row['version']}")

    def create_run(self, book: BookIdentity, run: RunIdentity, owner_id: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO books VALUES (?, ?, ?, ?)",
                (book.book_id, book.source_hash, book.filename, now),
            )
            conn.execute(
                "INSERT INTO runs(run_id,book_id,owner_id,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (run.run_id, run.book_id, owner_id, RunState.CREATED.value, now, now),
            )

    def transition(self, run_id: str, state: RunState, checkpoint: dict | None = None,
                   error_code: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            current = conn.execute(
                "SELECT state FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if current is None:
                raise KeyError(run_id)
            current_state = RunState(current["state"])
            if state != current_state and state not in RUN_TRANSITIONS[current_state]:
                raise ValueError(
                    f"Invalid run transition: {current_state.value} -> {state.value}"
                )
            conn.execute(
                "UPDATE runs SET state=?, checkpoint=?, error_code=?, updated_at=? WHERE run_id=?",
                (state.value, json.dumps(checkpoint or {}), error_code, time.time(), run_id),
            ).rowcount
            conn.execute(
                "INSERT INTO events(run_id,event_type,payload,created_at) VALUES(?,?,?,?)",
                (run_id, "run.transition", json.dumps({"state": state.value}), time.time()),
            )

    def get_run(self, run_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM runs WHERE run_id=?"
        params: tuple[Any, ...] = (run_id,)
        if owner_id is not None:
            query += " AND owner_id=?"
            params += (owner_id,)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def save_segment(self, run_id: str, segment: Segment,
                     provenance: dict | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO segments
                   (segment_id,run_id,chapter_id,ordinal,source_hash,source_text,
                    translation,state,score,revision,issues,provenance)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(segment_id) DO UPDATE SET
                    translation=excluded.translation,state=excluded.state,
                    score=excluded.score,revision=excluded.revision,
                    issues=excluded.issues,provenance=excluded.provenance""",
                (segment.segment_id, run_id, segment.chapter_id, segment.ordinal,
                 segment.source_hash, segment.source_text, segment.translation,
                 segment.state.value, segment.score, segment.revision,
                 json.dumps(segment.issues, ensure_ascii=False),
                 json.dumps(provenance or {}, ensure_ascii=False)),
            )

    def accepted_translation(self, run_id: str, segment_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT translation FROM segments WHERE run_id=? AND segment_id=? AND state=?",
                (run_id, segment_id, SegmentState.ACCEPTED.value),
            ).fetchone()
        return row[0] if row else None

    def memory_put(self, book_id: str, namespace: str, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory(book_id,namespace,key,value,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(book_id,namespace,key) DO UPDATE SET
                   value=excluded.value,version=memory.version+1,updated_at=excluded.updated_at""",
                (book_id, namespace, key, encoded, time.time()),
            )

    def memory_get(self, book_id: str, namespace: str, key: str,
                   default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM memory WHERE book_id=? AND namespace=? AND key=?",
                (book_id, namespace, key),
            ).fetchone()
        return json.loads(row[0]) if row else default

    def memory_summary(self, book_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT namespace,COUNT(*) count FROM memory WHERE book_id=? GROUP BY namespace",
                (book_id,),
            ).fetchall()
        return {row["namespace"]: row["count"] for row in rows}

    def create_api_job(self, job_id: str, owner_id: str, payload: dict[str, Any],
                       max_jobs: int = 50) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM api_jobs").fetchone()[0]
            if total >= max_jobs:
                removable = conn.execute(
                    "SELECT job_id FROM api_jobs WHERE status IN ('done','error') "
                    "ORDER BY created_at LIMIT ?", (total - max_jobs + 1,),
                ).fetchall()
                if not removable:
                    raise OverflowError("ASOST API job queue is full")
                conn.executemany(
                    "DELETE FROM api_jobs WHERE job_id=?",
                    [(row["job_id"],) for row in removable],
                )
            conn.execute(
                "INSERT INTO api_jobs VALUES(?,?,?,?,NULL,NULL,?,?)",
                (job_id, owner_id, "queued", json.dumps(payload, ensure_ascii=False), now, now),
            )

    def update_api_job(self, job_id: str, status: str, *, result: Any = None,
                       error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            changed = conn.execute(
                "UPDATE api_jobs SET status=?,result=?,error=?,updated_at=? WHERE job_id=?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, time.time(), job_id),
            ).rowcount
            if changed != 1:
                raise KeyError(job_id)

    def get_api_job(self, job_id: str, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_jobs WHERE job_id=? AND owner_id=?",
                (job_id, owner_id),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value
