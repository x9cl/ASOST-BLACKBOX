"""SQLite-backed repository shared by the ASOST components.

Values are JSON encoded, but updates are real SQLite transactions rather than
JSON-file read/modify/write cycles.  Every record is isolated by the complete
translation namespace, preventing separate books and agent runs from leaking
state into one another.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemoryNamespace:
    book_id: str
    run_id: str
    agent_role: str
    chapter_id: str
    segment_id: str

    def values(self) -> tuple[str, ...]:
        values = tuple(getattr(self, f.name) for f in fields(self))
        if any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("all namespace fields must be non-empty strings")
        return values


class SQLiteMemoryRepository:
    """Process-safe repository using WAL and transactional migrations."""

    def __init__(self, path: os.PathLike[str] | str | None = None):
        default = os.environ.get("ASOST_MEMORY_DB", "/opt/data/projects/assost/asost_memory.db")
        self.path = Path(path or default)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def _migrate(self) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"memory schema {version} is newer than supported {SCHEMA_VERSION}")
            if version < 1:
                con.executescript("""
                CREATE TABLE memory (
                  book_id TEXT NOT NULL, run_id TEXT NOT NULL, agent_role TEXT NOT NULL,
                  chapter_id TEXT NOT NULL, segment_id TEXT NOT NULL, key TEXT NOT NULL,
                  value_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                  updated_at REAL NOT NULL,
                  PRIMARY KEY (book_id,run_id,agent_role,chapter_id,segment_id,key));
                CREATE TABLE events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  book_id TEXT NOT NULL, run_id TEXT NOT NULL, agent_role TEXT NOT NULL,
                  chapter_id TEXT NOT NULL, segment_id TEXT NOT NULL,
                  event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE checkpoints (
                  book_id TEXT NOT NULL, run_id TEXT NOT NULL, agent_role TEXT NOT NULL,
                  chapter_id TEXT NOT NULL, segment_id TEXT NOT NULL, name TEXT NOT NULL,
                  snapshot_json TEXT NOT NULL, created_at REAL NOT NULL,
                  PRIMARY KEY (book_id,run_id,agent_role,chapter_id,segment_id,name));
                CREATE INDEX events_namespace_idx ON events
                  (book_id,run_id,agent_role,chapter_id,segment_id,id);
                PRAGMA user_version=1;
                """)
            con.commit()

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def get(self, namespace: MemoryNamespace, key: str, default: Any = None) -> Any:
        with self._connect() as con:
            row = con.execute(
                "SELECT value_json FROM memory WHERE book_id=? AND run_id=? AND agent_role=? "
                "AND chapter_id=? AND segment_id=? AND key=?", namespace.values() + (key,),
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def get_with_revision(self, namespace: MemoryNamespace, key: str) -> tuple[Any, Optional[int]]:
        with self._connect() as con:
            row = con.execute(
                "SELECT value_json,revision FROM memory WHERE book_id=? AND run_id=? AND agent_role=? "
                "AND chapter_id=? AND segment_id=? AND key=?", namespace.values() + (key,),
            ).fetchone()
        return (None, None) if row is None else (json.loads(row[0]), row[1])

    def put(self, namespace: MemoryNamespace, key: str, value: Any) -> int:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT INTO memory VALUES (?,?,?,?,?,?,?,1,?) ON CONFLICT "
                        "(book_id,run_id,agent_role,chapter_id,segment_id,key) DO UPDATE SET "
                        "value_json=excluded.value_json,revision=memory.revision+1,updated_at=excluded.updated_at",
                        namespace.values() + (key, self._dump(value), time.time()))
            revision = con.execute(
                "SELECT revision FROM memory WHERE book_id=? AND run_id=? AND agent_role=? "
                "AND chapter_id=? AND segment_id=? AND key=?", namespace.values() + (key,),
            ).fetchone()[0]
            con.commit()
            return revision

    def compare_and_set(self, namespace: MemoryNamespace, key: str,
                        expected_revision: Optional[int], value: Any) -> bool:
        """Atomically update a revision, or insert only when expected is None."""
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if expected_revision is None:
                cur = con.execute("INSERT OR IGNORE INTO memory VALUES (?,?,?,?,?,?,?,1,?)",
                                  namespace.values() + (key, self._dump(value), time.time()))
            else:
                cur = con.execute(
                    "UPDATE memory SET value_json=?,revision=revision+1,updated_at=? WHERE "
                    "book_id=? AND run_id=? AND agent_role=? AND chapter_id=? AND segment_id=? "
                    "AND key=? AND revision=?",
                    (self._dump(value), time.time()) + namespace.values() + (key, expected_revision))
            con.commit()
            return cur.rowcount == 1

    def append_event(self, namespace: MemoryNamespace, event_type: str, payload: Any) -> int:
        with self._connect() as con:
            cur = con.execute("INSERT INTO events (book_id,run_id,agent_role,chapter_id,segment_id,"
                              "event_type,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                              namespace.values() + (event_type, self._dump(payload), time.time()))
            return cur.lastrowid

    def commit_accepted_translation(self, namespace: MemoryNamespace, source: str,
                                    translation: str, metadata: Any = None) -> int:
        """Atomically persist an accepted translation and its audit event."""
        payload = {"source": source, "translation": translation, "metadata": metadata or {}}
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT INTO memory VALUES (?,?,?,?,?,?,?,1,?) ON CONFLICT "
                        "(book_id,run_id,agent_role,chapter_id,segment_id,key) DO UPDATE SET "
                        "value_json=excluded.value_json,revision=memory.revision+1,updated_at=excluded.updated_at",
                        namespace.values() + ("accepted_translation", self._dump(payload), time.time()))
            cur = con.execute("INSERT INTO events (book_id,run_id,agent_role,chapter_id,segment_id,"
                              "event_type,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                              namespace.values() + ("translation.accepted", self._dump(payload), time.time()))
            con.commit()
            return cur.lastrowid

    def create_checkpoint(self, namespace: MemoryNamespace, name: str) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute("SELECT key,value_json,revision FROM memory WHERE book_id=? AND run_id=? "
                               "AND agent_role=? AND chapter_id=? AND segment_id=?", namespace.values()).fetchall()
            snapshot = {k: [json.loads(v), rev] for k, v, rev in rows}
            con.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?,?) ON CONFLICT "
                        "(book_id,run_id,agent_role,chapter_id,segment_id,name) DO UPDATE SET "
                        "snapshot_json=excluded.snapshot_json,created_at=excluded.created_at",
                        namespace.values() + (name, self._dump(snapshot), time.time()))
            con.commit()

    def restore_checkpoint(self, namespace: MemoryNamespace, name: str) -> bool:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT snapshot_json FROM checkpoints WHERE book_id=? AND run_id=? "
                              "AND agent_role=? AND chapter_id=? AND segment_id=? AND name=?",
                              namespace.values() + (name,)).fetchone()
            if row is None:
                con.rollback(); return False
            con.execute("DELETE FROM memory WHERE book_id=? AND run_id=? AND agent_role=? AND "
                        "chapter_id=? AND segment_id=?", namespace.values())
            for key, (value, revision) in json.loads(row[0]).items():
                con.execute("INSERT INTO memory VALUES (?,?,?,?,?,?,?,?,?)",
                            namespace.values() + (key, self._dump(value), revision, time.time()))
            con.commit(); return True
