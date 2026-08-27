"""Security regression tests for the ASOST dashboard API."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from asost import api


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ASOST_AUTH_TOKENS", json.dumps({
        "operator-token": "operator",
        "reviewer-token": "reviewer",
        "observer-token": "observer",
        "admin-token": "admin",
    }))
    monkeypatch.delenv("ASOST_API_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/api/asost/memory",
    "/api/asost/agents",
    "/api/asost/status/missing",
])
@pytest.mark.parametrize("headers", [{}, {"X-ASOST-Token": "invalid"}])
def test_read_endpoints_reject_missing_or_invalid_credentials(client, path, headers):
    response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert "invalid" not in response.text


@pytest.mark.parametrize("role", ["reviewer", "observer"])
def test_non_writers_receive_403(client, role):
    response = client.post(
        "/api/asost/translate-page",
        headers={"X-ASOST-Token": f"{role}-token"},
        json={"page_num": 1, "src_text": "private book text"},
    )

    assert response.status_code == 403
    assert "private book text" not in response.text
    assert f"{role}-token" not in response.text


@pytest.mark.parametrize("role", ["operator", "reviewer", "observer", "admin"])
def test_all_roles_have_authenticated_read_access(client, role):
    response = client.get(
        "/api/asost/memory", headers={"X-ASOST-Token": f"{role}-token"}
    )

    assert response.status_code == 200
    assert set(response.json()) == {"exists", "summary"}


def test_memory_returns_counts_without_path_content_or_credentials(
    client, monkeypatch, tmp_path
):
    memory_path = tmp_path / "private" / "asost_memory.json"
    memory_path.parent.mkdir()
    memory_path.write_text(json.dumps({
        "books": [
            {"title": "SECRET BOOK TEXT", "chapters": ["chapter one", "chapter two"]},
            {"title": "another", "chapters": ["chapter three"]},
        ],
        "glossary": {"private term": "private definition"},
        "credentials": {"api_key": "super-secret-key"},
    }), encoding="utf-8")
    monkeypatch.setattr(api, "MEMORY_PATH", memory_path)

    response = client.get(
        "/api/asost/memory", headers={"X-ASOST-Token": "observer-token"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "exists": True,
        "summary": {"books": 2, "chapters": 3, "terms": 1},
    }
    assert str(memory_path) not in response.text
    assert "SECRET BOOK TEXT" not in response.text
    assert "super-secret-key" not in response.text


def test_observer_status_omits_book_content_and_error_credentials(client):
    job_id = "security-test"
    api._jobs[job_id] = {
        "status": "done",
        "result": {"translation": "SECRET BOOK TEXT", "api_key": "secret-key"},
        "error": "failed with password=hunter2",
    }
    try:
        response = client.get(
            f"/api/asost/status/{job_id}",
            headers={"X-ASOST-Token": "observer-token"},
        )
    finally:
        api._jobs.pop(job_id, None)

    assert response.status_code == 200
    assert response.json() == {"status": "done"}
    assert "SECRET BOOK TEXT" not in response.text
    assert "secret-key" not in response.text
    assert "hunter2" not in response.text


def test_reviewer_status_redacts_structured_credentials(client):
    job_id = "review-test"
    api._jobs[job_id] = {
        "status": "done",
        "result": {"score": 90, "credentials": {"token": "secret-token"}},
        "error": None,
    }
    try:
        response = client.get(
            f"/api/asost/status/{job_id}",
            headers={"X-ASOST-Token": "reviewer-token"},
        )
    finally:
        api._jobs.pop(job_id, None)

    assert response.status_code == 200
    assert response.json()["result"] == {"score": 90, "credentials": "[REDACTED]"}
    assert "secret-token" not in response.text
