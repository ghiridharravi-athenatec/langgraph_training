'''POST /chat (ragchatbot/"Conversational Intelligence") is the single unified chat
entry point for both documents and a connected database - a bounded Supervisor
decision (app/core/orchestrator.py) picks whichever grounded source is available and
relevant, never falling back to the model's own general knowledge. These tests confirm
/chat genuinely uses a database connection when the user has one and no documents
(rather than ignoring it, as it used to), still answers from documents when that's the
only/better source, and that /database/chat's own endpoints keep their independent
database-chatbot permission gate exactly as before.
'''

from tests.conftest import parse_sse_response, seed_document


def _classify_question(self, question, model=None, history=None):
    return {"intent": "question", "confidence": 0.99, "guardrail_events": [], "tier3_skip": []}


def _grant(client, admin_headers, user_id, *projects):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions", json={"projects": list(projects)}, headers=admin_headers,
    )
    assert resp.status_code == 200


def test_chat_answers_from_the_database_when_that_is_the_only_source(client, admin_headers, monkeypatch):
    '''A user with a database connected but no documents now gets a real database
    answer through /chat - database_chat is the only available route, so no LLM
    routing call is spent deciding (single-route skip).'''
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    client.post(
        "/api/v1/database/connections",
        json={"name": "MES", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    monkeypatch.setattr(
        "app.api.v1.database.run_db_agent",
        lambda question, details, model=None, history=None, request_id=None: {
            "answer": "There are 3 open work orders.",
            "guardrail_events": [], "logs": ["fake"], "token_count": 5,
        },
    )

    def _fail_if_called(self, question, model=None, history=None):
        raise AssertionError("document_chat's own intent classification should never run when database_chat is the only route")

    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _fail_if_called)

    resp = client.post("/api/v1/chat", json={"question": "how many work orders are open"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == "There are 3 open work orders."
    assert body["routed_to"] == "database_chat"
    routing_event = next(e for e in body["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["available_routes"] == ["database_chat"]


def test_chat_answers_from_documents_when_that_is_the_only_source(client, admin_headers, admin_id, monkeypatch):
    '''A user with documents but no database connected still gets a document answer -
    document_chat is the only available route, so no LLM routing call is spent.'''
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _classify_question)
    seed_document(admin_id)

    def fake_invoke(state):
        return {
            "answer": "doc answer", "retrieved_chunks": [], "reranked_chunks": [], "context": "",
            "logs": ["fake"], "guardrail_events": [], "blocked": False, "token_count": 5,
        }

    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == "doc answer"
    assert body["routed_to"] == "document_chat"


def test_chat_routes_between_documents_and_database_when_both_available(client, admin_headers, admin_id, monkeypatch):
    '''With both sources available, the Supervisor's own routing call decides - never a
    silent default to one or the other.'''
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    client.post(
        "/api/v1/database/connections",
        json={"name": "MES", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    seed_document(admin_id)

    from app.core.llm_provider import LLMResult

    def _fake_generate_json(prompt, max_tokens, stage, model=None):
        return LLMResult(
            text='{"route": "database_chat", "reasoning": "about work orders"}',
            token_count=10, provider="claude",
            safety_event={"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"},
            log="fake",
        )

    monkeypatch.setattr("app.api.v1.api.llm_provider.generate_json", _fake_generate_json)

    def _fail_if_called(*a, **kw):
        raise AssertionError("a route the Supervisor didn't pick should never be called")

    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", _fail_if_called)
    monkeypatch.setattr(
        "app.api.v1.database.run_db_agent",
        lambda question, details, model=None, history=None, request_id=None: {
            "answer": "There are 3 open work orders.", "guardrail_events": [], "logs": ["fake"], "token_count": 5,
        },
    )

    resp = client.post("/api/v1/chat", json={"question": "how many work orders are open"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == "There are 3 open work orders."
    assert body["routed_to"] == "database_chat"
    routing_event = next(e for e in body["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert set(routing_event["available_routes"]) == {"document_chat", "database_chat"}
    assert routing_event["fallback_used"] is False


def test_chat_blocked_with_no_documents_and_no_database(client, admin_headers):
    '''No general-knowledge fallback exists - with nothing grounded to answer from, the
    turn is blocked outright rather than answered from the model's own knowledge.'''
    resp = client.post("/api/v1/chat", json={"question": "hello"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    source_check_event = next(e for e in body["guardrail_events"] if e["stage"] == "chat_source_check")
    assert source_check_event["passed"] is False
    assert not any(e["stage"] == "orchestrator_routing" for e in body["guardrail_events"])


def test_database_endpoints_require_database_chatbot_grant_not_ragchatbot(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, "ragchatbot")  # document access only, not database

    resp = client.get("/api/v1/database/connections", headers=user_headers)
    assert resp.status_code == 403


def test_database_endpoints_work_with_database_chatbot_grant(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: [])
    _grant(client, admin_headers, user_id, "database-chatbot")  # database access only, not ragchatbot

    resp = client.get("/api/v1/database/connections", headers=user_headers)
    assert resp.status_code == 200

    # And the reverse still holds - no ragchatbot grant means no access to /chat at all,
    # regardless of what it might route to internally.
    chat_resp = client.post("/api/v1/chat", json={"question": "hello"}, headers=user_headers)
    assert chat_resp.status_code == 403
