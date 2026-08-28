import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from asost import api


def _checkpoint(page=1):
    return {"resume_from": "translate", "page_num": page, "src_text": "text", "context": ""}


def test_repository_persists_supervisor_envelope_and_recovers_running(tmp_path):
    path = tmp_path / "jobs.db"
    store = api.JobRepository(path)
    job = store.create(owner_id="alice", book_id="book-7", checkpoint=_checkpoint())
    store.update(job["job_id"], status="RUNNING", started_at=api._now())

    recovered = api.JobRepository(path).get(job["job_id"])

    assert tuple(key for key in api.JobRepository.fields) == (
        "job_id", "owner_id", "book_id", "run_id", "status", "created_at",
        "started_at", "finished_at", "checkpoint", "error_code",
    )
    assert recovered["status"] == "INTERRUPTED"
    assert recovered["error_code"] == "SERVER_RESTART"
    assert recovered["checkpoint"]["resume_from"] == "translate"


def test_retention_never_deletes_non_terminal_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "MAX_JOBS", 2)
    store = api.JobRepository(tmp_path / "jobs.db")
    first = store.create(owner_id="alice", book_id="one", checkpoint=_checkpoint(1))
    second = store.create(owner_id="alice", book_id="two", checkpoint=_checkpoint(2))
    store.create(owner_id="alice", book_id="three", checkpoint=_checkpoint(3))

    assert store.get(first["job_id"])["status"] == "QUEUED"
    assert store.get(second["job_id"])["status"] == "QUEUED"

    store.update(first["job_id"], status="DONE", finished_at=api._now())
    store.create(owner_id="alice", book_id="four", checkpoint=_checkpoint(4))
    assert store.get(first["job_id"]) is None
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM asost_jobs WHERE status='QUEUED'").fetchone()[0] == 3


def test_owned_job_hides_other_owners(monkeypatch, tmp_path):
    store = api.JobRepository(tmp_path / "jobs.db")
    job = store.create(owner_id="alice", book_id="book", checkpoint=_checkpoint())
    monkeypatch.setattr(api, "STORE", store)

    assert api._owned_job(job["job_id"], "alice")["job_id"] == job["job_id"]
    with pytest.raises(HTTPException) as denied:
        api._owned_job(job["job_id"], "bob")
    assert denied.value.status_code == 404
