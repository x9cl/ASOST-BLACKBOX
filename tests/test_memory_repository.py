import multiprocessing as mp
import os
import sqlite3

from asost.memory import MemoryNamespace, SQLiteMemoryRepository


NS = MemoryNamespace("book", "run", "worker", "chapter", "segment")


def _increment(path, count):
    repo = SQLiteMemoryRepository(path)
    for _ in range(count):
        while True:
            value, revision = repo.get_with_revision(NS, "counter")
            if repo.compare_and_set(NS, "counter", revision, (value or 0) + 1):
                break


def _crash_after_commit(path):
    SQLiteMemoryRepository(path).put(NS, "durable", {"ok": True})
    os._exit(23)


def test_multiprocess_compare_and_set_has_no_lost_updates(tmp_path):
    path = tmp_path / "memory.db"
    processes = [mp.Process(target=_increment, args=(path, 40)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert SQLiteMemoryRepository(path).get(NS, "counter") == 160


def test_wal_crash_recovery_preserves_committed_write(tmp_path):
    path = tmp_path / "memory.db"
    process = mp.Process(target=_crash_after_commit, args=(path,))
    process.start(); process.join(30)
    assert process.exitcode == 23
    repo = SQLiteMemoryRepository(path)
    assert repo.get(NS, "durable") == {"ok": True}
    assert repo._connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_checkpoint_restore_and_atomic_accepted_translation(tmp_path):
    repo = SQLiteMemoryRepository(tmp_path / "memory.db")
    repo.put(NS, "progress", {"page": 2})
    repo.create_checkpoint(NS, "page-2")
    repo.put(NS, "progress", {"page": 9})
    repo.put(NS, "temporary", True)
    assert repo.restore_checkpoint(NS, "page-2")
    assert repo.get(NS, "progress") == {"page": 2}
    assert repo.get(NS, "temporary") is None
    event_id = repo.commit_accepted_translation(NS, "hello", "مرحبا", {"score": 98})
    assert event_id > 0
    assert repo.get(NS, "accepted_translation")["translation"] == "مرحبا"
    with sqlite3.connect(repo.path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM events WHERE event_type='translation.accepted'").fetchone()[0] == 1


def test_namespace_fields_are_mandatory(tmp_path):
    repo = SQLiteMemoryRepository(tmp_path / "memory.db")
    bad = MemoryNamespace("book", "", "role", "chapter", "segment")
    try:
        repo.get(bad, "key")
    except ValueError:
        pass
    else:
        raise AssertionError("empty namespace field was accepted")
