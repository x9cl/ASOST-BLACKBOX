"""Concurrency and execution-identity isolation tests for ASOST."""
import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "asost"))

import agent_runner  # noqa: E402
import orchestrator  # noqa: E402


class FakeAgent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def chat(self, message):
        if "Translate" in message:
            return f"translation:{self.session_id}"
        return '{"score": 95, "notes": []}'


def test_build_agent_propagates_complete_identity(monkeypatch):
    monkeypatch.setitem(sys.modules, "run_agent", types.SimpleNamespace(AIAgent=FakeAgent))
    agent = agent_runner.build_agent("translator", "book-a", "run-1", "worker-7")

    assert agent.session_id == "asost:book-a:run-1:translator"
    assert agent.pass_session_id is True
    assert (agent.user_id, agent.chat_id, agent.thread_id) == (
        "book-a", "run-1", "worker-7")
    assert agent.asost_execution_identity == {
        "book_id": "book-a",
        "run_id": "run-1",
        "agent_instance_id": "worker-7",
        "role": "translator",
        "session_id": "asost:book-a:run-1:translator",
        "memory_namespace": "asost:book-a:run-1",
        "checkpoint_namespace": "asost:book-a:run-1:translator",
    }


def test_two_books_in_parallel_do_not_share_sessions_memory_or_results(
        monkeypatch, tmp_path):
    memory_path = tmp_path / "memory.json"
    monkeypatch.setattr(orchestrator, "_memory_path", lambda: str(memory_path))

    def fake_build(name, book_id, run_id, agent_instance_id):
        role = name
        agent = FakeAgent(session_id=f"asost:{book_id}:{run_id}:{role}")
        agent.asost_execution_identity = {
            "memory_namespace": f"asost:{book_id}:{run_id}",
            "checkpoint_namespace": agent.session_id,
            "agent_instance_id": agent_instance_id,
        }
        return agent

    monkeypatch.setattr(orchestrator, "build_agent", fake_build)

    def run_book(book_id):
        supervisor = orchestrator.ASOSTOrchestrator(book_id, "same-run", "worker")
        result = supervisor.translate_page(3, "source text " * 8)
        return supervisor, result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run_book, ("book-a", "book-b")))

    supervisors = (first[0], second[0])
    results = (first[1], second[1])
    session_sets = [set(agent.session_id for agent in item._agents.values())
                    for item in supervisors]
    assert session_sets[0].isdisjoint(session_sets[1])
    assert supervisors[0].memory_namespace != supervisors[1].memory_namespace
    assert results[0]["translation"] != results[1]["translation"]
    assert results[0]["book_id"] != results[1]["book_id"]

    stored = json.loads(memory_path.read_text(encoding="utf-8"))
    assert set(stored) == {"asost:book-a:same-run", "asost:book-b:same-run"}
    assert stored["asost:book-a:same-run"]["page_3_result"]["book_id"] == "book-a"
    assert stored["asost:book-b:same-run"]["page_3_result"]["book_id"] == "book-b"
