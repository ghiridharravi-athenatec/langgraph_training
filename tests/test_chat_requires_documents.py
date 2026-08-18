from tests.conftest import parse_sse_response, seed_document


def _fail_if_classify_intent_is_called(self, question):
    raise AssertionError("classify_intent should never run when the caller has no documents")


def test_chat_blocked_when_caller_has_no_documents(client, admin_headers, monkeypatch):
    '''Proves the guardrail short-circuits before the expensive intent-classification
    call, not just that the final response looks blocked.'''
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _fail_if_classify_intent_is_called)

    resp = client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=admin_headers)
    assert resp.status_code == 200  # a guardrail block is a normal chat response, not an HTTP error
    body = parse_sse_response(resp)
    assert body["message"] == "Request blocked by knowledge base check"
    events = body["graph_response"]["guardrail_events"]
    documents_event = next(e for e in events if e["stage"] == "documents_check")
    assert documents_event["passed"] is False


def test_chat_blocked_even_for_a_greeting_when_no_documents(client, admin_headers, monkeypatch):
    '''The knowledge base guardrail runs before intent classification, so even a
    harmless "hi" is blocked - there's nothing for chat to do at all yet.'''
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _fail_if_classify_intent_is_called)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert parse_sse_response(resp)["message"] == "Request blocked by knowledge base check"


def test_admin_gets_no_exemption_from_the_documents_check(client, admin_headers, monkeypatch):
    '''Unlike quota, there's no admin bypass here - retrieval isolation has no admin
    exception, so neither does the guardrail that enforces it has something to search.'''
    monkeypatch.setattr("app.api.v1.api.IntentClassifier.classify_intent", _fail_if_classify_intent_is_called)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert parse_sse_response(resp)["message"] == "Request blocked by knowledge base check"


def test_chat_proceeds_once_caller_has_ingested_a_document(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    body = parse_sse_response(resp)
    assert body["message"] == "Chat completed successfully"
    events = body["graph_response"]["guardrail_events"]
    documents_event = next(e for e in events if e["stage"] == "documents_check")
    assert documents_event["passed"] is True


def test_blocked_by_documents_check_turn_is_still_persisted(client, admin_headers):
    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert resp.status_code == 200
    conversation_id = parse_sse_response(resp)["conversation_id"]

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[1]["blocked"] is True
