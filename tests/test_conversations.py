from tests.conftest import seed_document, signup


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
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    seed_document(admin_id)
    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert resp.status_code == 200
    returned_conversation_id = resp.json()["conversation_id"]
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
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
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
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    resp = client.post(
        "/api/v1/chat", json={"question": "hi", "conversation_id": "no-such-id"}, headers=admin_headers
    )
    assert resp.status_code == 404


def test_blocked_turn_is_still_persisted(client, admin_headers):
    resp = client.post("/api/v1/chat", json={"question": "u"}, headers=admin_headers)
    assert resp.status_code == 200

    conversations = client.get("/api/v1/conversations", headers=admin_headers).json()
    messages = client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=admin_headers).json()
    assert len(messages) == 2
    assert messages[1]["blocked"] is True
