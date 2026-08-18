from datetime import date

import pytest

from app.core import config, db_connections
from app.utils.mongo import (
    create_database_connection,
    delete_database_connection,
    get_database_connection,
    increment_usage,
    list_database_connections,
)
from tests.conftest import parse_sse_response, signup


# ---------------------------------------------------------------------------
# Read-only query guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM users",
    "select id, name from orders where id = 1",
    "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
])
def test_read_only_guard_allows_select(sql):
    db_connections._assert_read_only_sql(sql)  # does not raise


@pytest.mark.parametrize("sql", [
    "INSERT INTO users (name) VALUES ('x')",
    "UPDATE users SET name = 'x'",
    "DELETE FROM users",
    "DROP TABLE users",
    "ALTER TABLE users ADD COLUMN x INT",
    "TRUNCATE TABLE users",
    "CREATE TABLE x (id INT)",
    "GRANT ALL ON users TO someone",
])
def test_read_only_guard_rejects_write_statements(sql):
    with pytest.raises(db_connections.ConnectionError_):
        db_connections._assert_read_only_sql(sql)


def test_read_only_guard_rejects_multi_statement():
    with pytest.raises(db_connections.ConnectionError_):
        db_connections._assert_read_only_sql("SELECT * FROM users; DROP TABLE users;")


def test_read_only_guard_rejects_non_select_statement():
    with pytest.raises(db_connections.ConnectionError_):
        db_connections._assert_read_only_sql("EXEC sp_do_something")


def test_read_only_guard_catches_write_keyword_smuggled_after_select():
    '''A single statement that still contains a write keyword anywhere - e.g. a
    subquery attempting something cute - is rejected too, not just a bare
    leading write keyword.'''
    with pytest.raises(db_connections.ConnectionError_):
        db_connections._assert_read_only_sql("SELECT (DELETE FROM users) FROM dual")


# ---------------------------------------------------------------------------
# Connection detail normalization
# ---------------------------------------------------------------------------

def test_build_connection_details_from_connection_string():
    details = db_connections.build_connection_details(
        engine="postgresql", connection_string="postgresql://user:pw@host/db"
    )
    assert details["connection_string"] == "postgresql://user:pw@host/db"
    assert details["engine"] == "postgresql"


def test_build_connection_details_from_structured_fields():
    details = db_connections.build_connection_details(
        engine="mysql", host="db.example.com", port=3306, username="root", password="pw", database="app",
    )
    assert details["host"] == "db.example.com"
    assert details["database"] == "app"


def test_build_connection_details_requires_something():
    with pytest.raises(ValueError):
        db_connections.build_connection_details(engine="postgresql")


def test_build_connection_details_rejects_unknown_engine():
    with pytest.raises(ValueError):
        db_connections.build_connection_details(engine="oracle", connection_string="whatever")


# ---------------------------------------------------------------------------
# Credential encryption round-trip
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip():
    details = {"engine": "postgresql", "host": "h", "username": "u", "password": "secret", "database": "d"}
    token = db_connections.encrypt_connection_details(details)
    assert "secret" not in token
    assert db_connections.decrypt_connection_details(token) == details


def test_decrypt_rejects_garbage_token():
    with pytest.raises(db_connections.ConnectionError_):
        db_connections.decrypt_connection_details("not-a-real-token")


# ---------------------------------------------------------------------------
# Mongo CRUD (client fixture used only for its mongomock monkeypatch)
# ---------------------------------------------------------------------------

def test_database_connection_crud_round_trip(client):
    doc = create_database_connection(
        user_id="user-1", name="My DB", engine="postgresql",
        encrypted_details="encrypted-blob", database="app", host="db.example.com",
    )
    assert doc["_id"]

    fetched = get_database_connection(doc["_id"])
    assert fetched["name"] == "My DB"
    assert fetched["encrypted_details"] == "encrypted-blob"

    mine = list_database_connections(user_id="user-1")
    assert len(mine) == 1

    others = list_database_connections(user_id="someone-else")
    assert others == []

    assert delete_database_connection(doc["_id"]) is True
    assert get_database_connection(doc["_id"]) is None
    assert delete_database_connection(doc["_id"]) is False


# ---------------------------------------------------------------------------
# API endpoints (driver-level DB calls mocked - no real database involved)
# ---------------------------------------------------------------------------

def _grant_database_chatbot(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions", json={"projects": ["database-chatbot"]}, headers=admin_headers,
    )
    assert resp.status_code == 200


def test_create_connection_validates_before_saving(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users", "orders"])

    resp = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Prod"
    assert body["engine"] == "postgresql"
    assert "password" not in body
    assert "connection_string" not in body


def test_create_connection_rejects_unreachable_database(client, admin_headers, monkeypatch):
    def _fail(details):
        raise db_connections.ConnectionError_("could not connect")

    monkeypatch.setattr("app.core.db_connections.test_connection", _fail)

    resp = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_list_connections_scoped_to_caller(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: [])
    _grant_database_chatbot(client, admin_headers, user_id)

    client.post(
        "/api/v1/database/connections",
        json={"name": "Admin's DB", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    client.post(
        "/api/v1/database/connections",
        json={"name": "User's DB", "engine": "mysql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=user_headers,
    )

    admin_view = client.get("/api/v1/database/connections", headers=admin_headers).json()
    user_view = client.get("/api/v1/database/connections", headers=user_headers).json()
    assert [c["name"] for c in admin_view] == ["Admin's DB"]
    assert [c["name"] for c in user_view] == ["User's DB"]


def test_cannot_delete_or_chat_with_another_users_connection(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: [])
    _grant_database_chatbot(client, admin_headers, user_id)

    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Admin's DB", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    delete_resp = client.delete(f"/api/v1/database/connections/{created['id']}", headers=user_headers)
    assert delete_resp.status_code == 404

    chat_resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many rows?"},
        headers=user_headers,
    )
    assert chat_resp.status_code == 404


def test_database_chat_runs_agent_against_decrypted_connection(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])

    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    captured = {}

    def fake_run_db_agent(question, details, model=None, history=None, request_id=None):
        captured["question"] = question
        captured["details"] = details
        captured["model"] = model
        captured["history"] = history
        return {
            "answer": "There are 42 users.",
            "guardrail_events": [{"stage": "db_agent_tool_call", "tool": "run_query", "passed": True, "reason": None}],
            "logs": ["Answered using claude (claude-sonnet-5)"],
            "token_count": 123,
        }

    monkeypatch.setattr("app.api.v1.database.run_db_agent", fake_run_db_agent)

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users?", "model": "opus"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == "There are 42 users."
    assert body["message"] == "Chat completed successfully"
    assert body["conversation_id"]

    # The agent was handed the DECRYPTED spec, not the encrypted blob or raw payload.
    assert captured["details"]["host"] == "h"
    assert captured["details"]["username"] == "u"
    assert captured["model"] == "opus"
    assert captured["history"] == []  # first turn in a fresh conversation


def test_database_chat_auto_creates_conversation_and_persists_turns(client, admin_headers, monkeypatch):
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
        json={"connection_id": created["id"], "question": "how many users?"},
        headers=admin_headers,
    )
    chat_body = parse_sse_response(resp)
    conversation_id = chat_body["conversation_id"]
    turn_id = chat_body["turn_id"]
    assert turn_id

    messages = client.get(f"/api/v1/database/conversations/{conversation_id}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user" and messages[0]["content"] == "how many users?"
    assert messages[0]["id"] == turn_id
    assert messages[1]["role"] == "assistant" and messages[1]["content"] == "42 users."
    assert messages[1]["turn_id"] == turn_id

    conversations = client.get("/api/v1/database/conversations", headers=admin_headers).json()
    assert conversations[0]["connection_id"] == created["id"]

    # A document-chatbot conversation_id is a different project - it must 404 here,
    # never silently answer as if it were a database conversation.
    doc_conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]
    cross_project = client.get(
        f"/api/v1/database/conversations/{doc_conversation_id}/messages", headers=admin_headers
    )
    assert cross_project.status_code == 404


def test_database_chat_second_turn_receives_first_turns_history(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    captured = {}

    def fake_run_db_agent(question, details, model=None, history=None, request_id=None):
        captured["history"] = history
        return {"answer": "42 users.", "guardrail_events": [], "logs": [], "token_count": 0}

    monkeypatch.setattr("app.api.v1.database.run_db_agent", fake_run_db_agent)

    first = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users?"},
        headers=admin_headers,
    )
    conversation_id = parse_sse_response(first)["conversation_id"]
    assert captured["history"] == []

    client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "and how many orders?", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert captured["history"] == [
        {"role": "user", "content": "how many users?"},
        {"role": "assistant", "content": "42 users."},
    ]


def test_conversation_stays_pinned_to_its_original_connection(client, admin_headers, monkeypatch):
    '''A conversation is pinned to whichever connection it was started against -
    a later message naming a different connection_id is silently ignored in favor
    of the one already stored on the conversation, so history from one database
    can never get mixed into a query against another mid-conversation.'''
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    first_db = client.post(
        "/api/v1/database/connections",
        json={"name": "First", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()
    second_db = client.post(
        "/api/v1/database/connections",
        json={"name": "Second", "engine": "postgresql", "host": "h2", "username": "u", "password": "p", "database": "d2"},
        headers=admin_headers,
    ).json()

    captured = {}

    def fake_run_db_agent(question, details, model=None, history=None, request_id=None):
        captured["details"] = details
        return {"answer": "ok", "guardrail_events": [], "logs": [], "token_count": 0}

    monkeypatch.setattr("app.api.v1.database.run_db_agent", fake_run_db_agent)

    first = client.post(
        "/api/v1/database/chat",
        json={"connection_id": first_db["id"], "question": "hi"},
        headers=admin_headers,
    )
    conversation_id = parse_sse_response(first)["conversation_id"]
    assert captured["details"]["database"] == "d"

    client.post(
        "/api/v1/database/chat",
        json={"connection_id": second_db["id"], "question": "still on the first db?", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert captured["details"]["database"] == "d"  # still the first connection, not the second


def test_database_chat_response_includes_timing_and_persists_it(client, admin_headers, monkeypatch):
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
        json={"connection_id": created["id"], "question": "how many users?"},
        headers=admin_headers,
    )
    body = parse_sse_response(resp)
    assert isinstance(body["response_time_ms"], (int, float))
    assert body["response_time_ms"] >= 0

    messages = client.get(f"/api/v1/database/conversations/{body['conversation_id']}/messages", headers=admin_headers).json()
    assert messages[1]["response_time_ms"] == body["response_time_ms"]


def test_database_chat_answer_goes_through_the_output_guardrail(client, admin_headers, monkeypatch):
    '''Same output_validation pass (blocked-keyword check + PII masking) the
    document chatbot applies to its answers - proven here by swapping in a fake
    GuardrailsAgent.check_output rather than depending on Presidio's real NER
    detection, which is already covered by its own unit tests.'''
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    monkeypatch.setattr(
        "app.api.v1.database.run_db_agent",
        lambda question, details, model=None, history=None, request_id=None: {
            "answer": "The admin's email is admin@example.com.", "guardrail_events": [], "logs": [], "token_count": 0,
        },
    )
    monkeypatch.setattr(
        "app.core.guardrails_agent.guardrails_agent.check_output",
        lambda answer: {
            "stage": "output_validation", "passed": True, "reason": None,
            "sanitized_answer": "The admin's email is [EMAIL_MASKED].",
            "checks": [{"check": "pii_masking", "passed": True, "reason": None, "pii_detected": [{"entity_type": "EMAIL_ADDRESS", "count": 1}]}],
        },
    )
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "what is the admin's email?"},
        headers=admin_headers,
    )
    body = parse_sse_response(resp)
    assert body["answer"] == "The admin's email is [EMAIL_MASKED]."
    assert "admin@example.com" not in body["answer"]
    output_event = next(e for e in body["guardrail_events"] if e["stage"] == "output_validation")
    assert output_event["passed"] is True

    messages = client.get(f"/api/v1/database/conversations/{body['conversation_id']}/messages", headers=admin_headers).json()
    assert messages[1]["content"] == "The admin's email is [EMAIL_MASKED]."
    assert messages[1]["blocked"] is False


def test_database_chat_rejects_a_document_chatbot_conversation_id(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()
    doc_conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "hi", "conversation_id": doc_conversation_id},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_database_chat_gives_an_actionable_error_when_the_conversations_connection_was_deleted(
    client, admin_headers, monkeypatch
):
    '''Regression test: a conversation pinned to a connection that's since been deleted
    used to surface a bare "Database connection not found" - now it explains what
    happened and how to recover (see _get_owned_connection's not_found_detail).'''
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

    first = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users?"},
        headers=admin_headers,
    )
    conversation_id = parse_sse_response(first)["conversation_id"]

    assert client.delete(f"/api/v1/database/connections/{created['id']}", headers=admin_headers).status_code == 204

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users now?", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert resp.status_code == 404
    assert "deleted" in resp.json()["detail"].lower()
    assert "new chat" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Input guardrail + quota enforcement (parity with the document chatbot)
# ---------------------------------------------------------------------------

def test_database_chat_blocked_by_input_guardrail_never_reaches_the_agent(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    calls = {"n": 0}

    def fake_run_db_agent(question, details, model=None, history=None, request_id=None):
        calls["n"] += 1
        return {"answer": "should not run", "guardrail_events": [], "logs": [], "token_count": 0}

    monkeypatch.setattr("app.api.v1.database.run_db_agent", fake_run_db_agent)
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "u"},  # too short
        headers=admin_headers,
    )
    assert resp.status_code == 200
    chat_body = parse_sse_response(resp)
    assert chat_body["message"] == "Request blocked by input validation"
    assert calls["n"] == 0

    conversation_id = chat_body["conversation_id"]
    messages = client.get(f"/api/v1/database/conversations/{conversation_id}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[1]["blocked"] is True


def test_database_chat_blocked_by_quota(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    increment_usage(me["id"], date.today().isoformat(), config.DAILY_TOKEN_QUOTA)

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users are there"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert parse_sse_response(resp)["message"] == "Request blocked by quota"


# ---------------------------------------------------------------------------
# Editing a connection
# ---------------------------------------------------------------------------

def test_edit_connection_updates_fields_and_reconnects_with_new_credentials(client, admin_headers, monkeypatch):
    seen_details = []
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: seen_details.append(details) or ["users"])

    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "old-host", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    updated = client.put(
        f"/api/v1/database/connections/{created['id']}",
        json={"name": "Prod (renamed)", "engine": "postgresql", "host": "new-host", "username": "u2", "password": "p2", "database": "d2"},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == created["id"]
    assert body["name"] == "Prod (renamed)"
    assert body["host"] == "new-host"
    assert body["database"] == "d2"
    assert seen_details[-1]["host"] == "new-host"  # re-validated against the NEW details, not the old ones

    captured = {}

    def fake_run_db_agent(question, details, model=None, history=None, request_id=None):
        captured["details"] = details
        return {"answer": "ok", "guardrail_events": [], "logs": [], "token_count": 0}

    monkeypatch.setattr("app.api.v1.database.run_db_agent", fake_run_db_agent)
    client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users are there"},
        headers=admin_headers,
    )
    assert captured["details"]["host"] == "new-host"
    assert captured["details"]["username"] == "u2"


def test_edit_connection_rejects_unreachable_new_details(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    def _fail(details):
        raise db_connections.ConnectionError_("could not connect")

    monkeypatch.setattr("app.core.db_connections.test_connection", _fail)
    resp = client.put(
        f"/api/v1/database/connections/{created['id']}",
        json={"name": "Prod", "engine": "postgresql", "host": "unreachable", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_cannot_edit_another_users_connection(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: [])
    _grant_database_chatbot(client, admin_headers, user_id)

    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Admin's DB", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    resp = client.put(
        f"/api/v1/database/connections/{created['id']}",
        json={"name": "Hijacked", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=user_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tool-call trace persistence
# ---------------------------------------------------------------------------

def test_guardrail_events_round_trip_through_conversation_history(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["users"])
    monkeypatch.setattr(
        "app.api.v1.database.run_db_agent",
        lambda question, details, model=None, history=None, request_id=None: {
            "answer": "42 users.",
            "guardrail_events": [{"stage": "db_agent_tool_call", "tool": "run_query", "passed": True, "reason": None}],
            "logs": [],
            "token_count": 0,
        },
    )
    created = client.post(
        "/api/v1/database/connections",
        json={"name": "Prod", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    ).json()

    resp = client.post(
        "/api/v1/database/chat",
        json={"connection_id": created["id"], "question": "how many users are there"},
        headers=admin_headers,
    )
    conversation_id = parse_sse_response(resp)["conversation_id"]

    messages = client.get(f"/api/v1/database/conversations/{conversation_id}/messages", headers=admin_headers).json()
    tool_events = [e for e in messages[1]["guardrail_events"] if e["stage"] == "db_agent_tool_call"]
    assert tool_events == [{"stage": "db_agent_tool_call", "tool": "run_query", "passed": True, "reason": None}]
