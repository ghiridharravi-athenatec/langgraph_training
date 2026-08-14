from datetime import date

from app.core import config
from app.utils.mongo import increment_usage
from tests.conftest import seed_document


def _grant_ragchatbot(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def test_user_blocked_once_daily_quota_exhausted(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    _grant_ragchatbot(client, admin_headers, user_id)
    seed_document(user_id)

    increment_usage(user_id, date.today().isoformat(), config.DAILY_TOKEN_QUOTA)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    body = resp.json()
    assert resp.status_code == 200  # quota block is a normal chat response, not an HTTP error
    assert body["message"] == "Request blocked by quota"
    events = body["graph_response"]["guardrail_events"]
    quota_event = next(e for e in events if e["stage"] == "quota_check")
    assert quota_event["passed"] is False


def test_admin_blocked_by_quota_like_any_user(client, admin_headers, monkeypatch):
    '''Admins are no longer unconditionally exempt - they fall back to the global
    default quota like anyone else unless they set their own per-user override.'''
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    seed_document(me["id"])
    increment_usage(me["id"], date.today().isoformat(), config.DAILY_TOKEN_QUOTA)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Request blocked by quota"


def test_admin_can_raise_own_quota_override(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    seed_document(me["id"])
    increment_usage(me["id"], date.today().isoformat(), config.DAILY_TOKEN_QUOTA)

    resp = client.put(
        f"/api/v1/admin/users/{me['id']}/quota",
        json={"daily_token_quota": config.DAILY_TOKEN_QUOTA * 10},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["daily_token_quota"] == config.DAILY_TOKEN_QUOTA * 10

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Chat completed successfully"


def test_admin_can_set_per_user_quota_for_another_user(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    _grant_ragchatbot(client, admin_headers, user_id)
    seed_document(user_id)
    increment_usage(user_id, date.today().isoformat(), config.DAILY_TOKEN_QUOTA - 10)

    resp = client.put(
        f"/api/v1/admin/users/{user_id}/quota",
        json={"daily_token_quota": 5},
        headers=admin_headers,
    )
    assert resp.status_code == 200

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Request blocked by quota"


def test_usage_below_quota_passes(client, admin_headers, user_headers, user_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    _grant_ragchatbot(client, admin_headers, user_id)
    seed_document(user_id)
    increment_usage(user_id, date.today().isoformat(), config.DAILY_TOKEN_QUOTA - 10)

    resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Chat completed successfully"
