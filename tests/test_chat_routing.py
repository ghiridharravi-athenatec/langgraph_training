'''The document chatbot (ragchatbot) and database chatbot (database-chatbot) are
two separate projects now - no auto-routing between them. These tests confirm
POST /chat never touches database connections at all (so a user with only a
database connected and no documents still hits the "no documents" guardrail
rather than silently answering from a database), and that /database/chat and
its connection-management endpoints require the new database-chatbot grant
instead of ragchatbot.
'''

from tests.conftest import parse_sse_response, seed_document


def _classify_question(self, question, model=None):
    return {"intent": "question", "confidence": 0.99, "guardrail_events": []}


def _grant(client, admin_headers, user_id, *projects):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions", json={"projects": list(projects)}, headers=admin_headers,
    )
    assert resp.status_code == 200


def test_chat_ignores_database_connections_entirely(client, admin_headers, monkeypatch):
    '''A user with a database connected but no documents still gets blocked by the
    document-only "no documents" guardrail on /chat - the database chatbot is a
    fully separate project now, not a fallback source for this endpoint.'''
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _classify_question)
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    client.post(
        "/api/v1/database/connections",
        json={"name": "MES", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )

    resp = client.post("/api/v1/chat", json={"question": "how many work orders are open"}, headers=admin_headers)
    assert resp.status_code == 200
    events = parse_sse_response(resp)["graph_response"]["guardrail_events"]
    documents_event = next(e for e in events if e["stage"] == "documents_check")
    assert documents_event["passed"] is False
    assert not any(e["stage"] == "chat_source_routing" for e in events)


def test_chat_answers_from_documents_when_a_database_is_also_connected(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _classify_question)
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    client.post(
        "/api/v1/database/connections",
        json={"name": "MES", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    seed_document(admin_id)

    def fake_invoke(state):
        return {
            "answer": "doc answer", "retrieved_chunks": [], "reranked_chunks": [], "context": "",
            "logs": ["fake"], "guardrail_events": [], "blocked": False, "token_count": 5,
        }

    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say"}, headers=admin_headers)
    assert resp.status_code == 200
    assert parse_sse_response(resp)["answer"] == "doc answer"


def test_database_endpoints_require_database_chatbot_grant_not_ragchatbot(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, "ragchatbot")  # document access only, not database

    resp = client.get("/api/v1/database/connections", headers=user_headers)
    assert resp.status_code == 403


def test_database_endpoints_work_with_database_chatbot_grant(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: [])
    _grant(client, admin_headers, user_id, "database-chatbot")  # database access only, not ragchatbot

    resp = client.get("/api/v1/database/connections", headers=user_headers)
    assert resp.status_code == 200

    # And the reverse still holds - no ragchatbot grant means no document chat.
    chat_resp = client.post("/api/v1/chat", json={"question": "hello"}, headers=user_headers)
    assert chat_resp.status_code == 403
