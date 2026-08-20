from app.core import progress
from tests.conftest import seed_document


def test_get_returns_none_for_unknown_request_id():
    assert progress.get("no-such-request") is None


def test_start_sets_the_default_reading_stage():
    progress.start("req-1")
    try:
        assert progress.get("req-1") == "Reading your question…"
    finally:
        progress.finish("req-1")


def test_update_overwrites_the_stage():
    progress.start("req-2")
    try:
        progress.update("req-2", "Drafting an answer…")
        assert progress.get("req-2") == "Drafting an answer…"
    finally:
        progress.finish("req-2")


def test_update_is_a_noop_for_a_request_id_that_was_never_started():
    progress.update("req-never-started", "Drafting an answer…")
    assert progress.get("req-never-started") is None


def test_finish_removes_the_entry():
    progress.start("req-3")
    progress.finish("req-3")
    assert progress.get("req-3") is None


def test_start_update_finish_are_noops_on_falsy_request_id():
    # Never raises, never creates a phantom entry - older/malformed requests that
    # don't send a request_id at all just get no live progress.
    progress.start(None)
    progress.update(None, "Drafting an answer…")
    progress.update("", "Drafting an answer…")
    progress.finish(None)
    assert progress.get(None) is None


def test_stale_entries_are_evicted():
    # Backdate the entry's timestamp directly rather than sleeping past the TTL -
    # deterministic, and avoids any dependency on real wall-clock timing/precision.
    progress.start("req-stale")
    progress._progress["req-stale"]["updated_at"] -= progress._TTL_SECONDS + 1
    assert progress.get("req-stale") is None


def test_progress_endpoint_requires_auth(client):
    resp = client.get("/api/v1/progress/some-request-id")
    assert resp.status_code == 401


def test_progress_endpoint_returns_null_stage_for_unknown_id(client, admin_headers):
    resp = client.get("/api/v1/progress/no-such-request", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"stage": None}


def test_progress_endpoint_reports_a_started_stage(client, admin_headers):
    progress.start("req-endpoint-test")
    try:
        resp = client.get("/api/v1/progress/req-endpoint-test", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"stage": "Reading your question…"}
    finally:
        progress.finish("req-endpoint-test")


def test_chat_request_cleans_up_its_progress_entry_when_done(client, admin_headers, admin_id, monkeypatch):
    '''By the time /chat has returned, its request_id's progress entry should
    already be gone (see api.py's finally: progress.finish(...)) - a client that
    keeps polling after the answer arrives shouldn't see stale/leftover state.'''
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    resp = client.post(
        "/api/v1/chat", json={"question": "hello there", "request_id": "req-doc-chat"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert progress.get("req-doc-chat") is None


def test_database_chat_request_cleans_up_its_progress_entry_when_done(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    monkeypatch.setattr(
        "app.api.v1.database.run_db_agent",
        lambda question, details, model=None, history=None, request_id=None: {
            "answer": "42 users.", "guardrail_events": [], "logs": [], "token_count": 0,
        },
    )
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users?", "request_id": "req-db-chat"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert progress.get("req-db-chat") is None
