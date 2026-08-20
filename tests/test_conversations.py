from app.utils.mongo import add_message, create_conversation
from tests.conftest import parse_sse_response, seed_document, signup


def _grant_ragchatbot(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_conversations(client, admin_headers):
    create = client.post("/api/v1/conversations", headers=admin_headers)
    assert create.status_code == 201
    body = create.json()
    assert body["title"] == "New chat"

    listing = client.get("/api/v1/conversations", headers=admin_headers)
    assert listing.status_code == 200
    assert body["id"] in [c["id"] for c in listing.json()]


def test_new_conversation_has_no_messages(client, admin_headers):
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]
    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=admin_headers)
    assert messages.status_code == 200
    assert messages.json() == []


def test_rename_conversation(client, admin_headers):
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]
    renamed = client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "My renamed chat"}, headers=admin_headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "My renamed chat"


def test_delete_conversation(client, admin_headers):
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]
    assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=admin_headers).status_code == 200

    listing = client.get("/api/v1/conversations", headers=admin_headers)
    assert conversation_id not in [c["id"] for c in listing.json()]


def test_user_cannot_access_another_users_conversation(client, admin_headers):
    alice = signup(client, "alice@example.com")
    bob = signup(client, "bob@example.com")
    _grant_ragchatbot(client, admin_headers, alice["user"]["id"])
    _grant_ragchatbot(client, admin_headers, bob["user"]["id"])

    alice_headers = _auth_headers(alice["access_token"])
    bob_headers = _auth_headers(bob["access_token"])

    conversation_id = client.post("/api/v1/conversations", headers=alice_headers).json()["id"]

    assert client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=bob_headers).status_code == 404
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "hijacked"}, headers=bob_headers
    ).status_code == 404
    assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=bob_headers).status_code == 404

    bob_list = client.get("/api/v1/conversations", headers=bob_headers)
    assert conversation_id not in [c["id"] for c in bob_list.json()]


def test_unauthenticated_blocked(client):
    assert client.get("/api/v1/conversations").status_code == 401


def test_conversations_require_ragchatbot_permission(client, user_headers):
    resp = client.get("/api/v1/conversations", headers=user_headers)
    assert resp.status_code == 403


def test_chat_auto_creates_conversation_and_persists_history(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert resp.status_code == 200
    returned_conversation_id = parse_sse_response(resp)["conversation_id"]
    assert returned_conversation_id

    conversations = client.get("/api/v1/conversations", headers=admin_headers).json()
    assert len(conversations) == 1
    assert conversations[0]["id"] == returned_conversation_id
    assert conversations[0]["title"] == "hello there"

    messages = client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello there"
    assert messages[1]["role"] == "assistant"


def test_chat_with_explicit_conversation_id_reuses_it(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]

    client.post("/api/v1/chat", json={"question": "hi", "conversation_id": conversation_id}, headers=admin_headers)
    client.post("/api/v1/chat", json={"question": "hi again", "conversation_id": conversation_id}, headers=admin_headers)

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=admin_headers).json()
    assert len(messages) == 4

    conversations = client.get("/api/v1/conversations", headers=admin_headers).json()
    assert len(conversations) == 1  # both turns landed in the same conversation, no extras created


def test_chat_with_unknown_conversation_id_404s(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    resp = client.post(
        "/api/v1/chat", json={"question": "hi", "conversation_id": "no-such-id"}, headers=admin_headers
    )
    assert resp.status_code == 404


def test_chat_response_turn_id_matches_persisted_message(client, admin_headers, admin_id, monkeypatch):
    '''turn_id (the question message's own id) powers the chat screen's "View Trace"
    link - GET /traces/turns/{turn_id} - and must match what the assistant message
    is later persisted with.'''
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    chat_body = parse_sse_response(resp)
    turn_id = chat_body["turn_id"]
    assert turn_id

    conversation_id = chat_body["conversation_id"]
    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=admin_headers).json()
    assert messages[0]["id"] == turn_id  # the user message's own id...
    assert messages[1]["turn_id"] == turn_id  # ...is what the assistant message points back to


def test_historical_messages_without_stored_turn_id_get_it_backfilled(client, admin_headers, admin_id):
    '''Messages persisted before turn_id existed never got that field written - "View
    Trace" on old conversations still needs to work, so list_messages backfills it by
    pairing with the preceding user message rather than requiring a data migration.'''
    conversation = create_conversation(admin_id, "ragchatbot")
    question = add_message(conversation["_id"], admin_id, "user", "an old question")
    add_message(conversation["_id"], admin_id, "assistant", "an old answer")  # no turn_id, like pre-feature data

    messages = client.get(f"/api/v1/conversations/{conversation['_id']}/messages", headers=admin_headers).json()
    assert messages[0]["id"] == question["_id"]
    assert messages[1]["turn_id"] == question["_id"]

    # And the deep-link endpoint resolves it too, since it derives via the same pairing.
    resp = client.get(f"/api/v1/traces/turns/{question['_id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["answer"] == "an old answer"


def test_blocked_turn_is_still_persisted(client, admin_headers):
    resp = client.post("/api/v1/chat", json={"question": "u"}, headers=admin_headers)
    assert resp.status_code == 200

    conversations = client.get("/api/v1/conversations", headers=admin_headers).json()
    messages = client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[1]["blocked"] is True


def _fake_graph_invoke_capturing_history():
    captured = {"history": None}

    def fake_invoke(state):
        captured["history"] = state.history
        return {
            "answer": "some answer",
            "retrieved_chunks": [], "reranked_chunks": [], "context": "",
            "logs": ["fake"], "guardrail_events": [], "blocked": False, "token_count": 0,
        }

    return captured, fake_invoke


def test_second_turn_receives_first_turns_history(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]

    captured, fake_invoke = _fake_graph_invoke_capturing_history()
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)

    client.post(
        "/api/v1/chat", json={"question": "what is the warranty", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert captured["history"] == []  # first turn in the conversation has no prior history

    client.post(
        "/api/v1/chat", json={"question": "and the return policy", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert captured["history"] == [
        {"role": "user", "content": "what is the warranty"},
        {"role": "assistant", "content": "some answer"},
    ]


def test_history_excludes_blocked_turns(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None, history=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    conversation_id = client.post("/api/v1/conversations", headers=admin_headers).json()["id"]

    # "u" is too short - blocked by input validation before the graph ever runs.
    client.post(
        "/api/v1/chat", json={"question": "u", "conversation_id": conversation_id}, headers=admin_headers,
    )

    captured, fake_invoke = _fake_graph_invoke_capturing_history()
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)
    client.post(
        "/api/v1/chat", json={"question": "what is the warranty", "conversation_id": conversation_id},
        headers=admin_headers,
    )
    assert captured["history"] == []  # the blocked turn isn't fed back in as context
