def _grant(client, admin_headers, user_id, project_ids):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": project_ids},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    return resp


def test_fresh_signup_has_no_visible_projects(client, user_headers):
    resp = client.get("/api/v1/projects", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_sees_all_enabled_projects(client, admin_headers):
    resp = client.get("/api/v1/projects", headers=admin_headers)
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert "ragchatbot" in ids


def test_unauthenticated_chat_and_ingest_401(client):
    assert client.post("/api/v1/chat", json={"question": "hello there"}).status_code == 401
    assert client.post("/api/v1/ingest", files={"file": ("a.pdf", b"x", "application/pdf")}).status_code == 401


def test_user_without_permission_403_on_ragchatbot_endpoints(client, user_headers):
    chat = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert chat.status_code == 403

    ingest = client.post(
        "/api/v1/ingest",
        files={"file": ("a.pdf", b"x", "application/pdf")},
        headers=user_headers,
    )
    assert ingest.status_code == 403

    assert client.get("/api/v1/documents", headers=user_headers).status_code == 403


def test_user_gains_access_after_grant_and_loses_it_after_revoke(
    client, monkeypatch, admin_headers, user_headers, user_id
):
    # Skip the real LLM/vector-search pipeline - only the authorization boundary is under test here.
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )

    before = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert before.status_code == 403

    _grant(client, admin_headers, user_id, ["ragchatbot"])

    visible = client.get("/api/v1/projects", headers=user_headers)
    assert [p["id"] for p in visible.json()] == ["ragchatbot"]

    after_grant = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert after_grant.status_code == 200

    _grant(client, admin_headers, user_id, [])

    after_revoke = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert after_revoke.status_code == 403

    visible_after_revoke = client.get("/api/v1/projects", headers=user_headers)
    assert visible_after_revoke.json() == []


def test_admin_can_access_ragchatbot_without_explicit_grant(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert resp.status_code == 200
