from app.core import config

PDF_BYTES = b"%PDF-1.4\n%fake pdf content for testing\n%%EOF"


def test_chat_rate_limit_blocks_after_threshold(client, user_headers, admin_headers, user_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    grant = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert grant.status_code == 200

    for i in range(config.CHAT_RATE_LIMIT):
        resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
        assert resp.status_code == 200, f"call {i} unexpectedly failed: {resp.text}"

    over_limit = client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)
    assert over_limit.status_code == 429
    assert "Retry-After" in over_limit.headers


def test_ingest_rate_limit_blocks_after_threshold(client, admin_headers, monkeypatch):
    import app.utils.ingest_files as ingest_files_module

    monkeypatch.setattr(
        ingest_files_module,
        "ingest_files",
        lambda file_paths, user_id, pii_entities=None: {
            "passed": True,
            "message": "ok",
            "pii_event": {"check": "pii_masking", "passed": True, "reason": None, "pii_detected": []},
            "chunk_count": 1,
            "extracted_text": "content",
        },
    )

    for i in range(config.INGEST_RATE_LIMIT):
        resp = client.post(
            "/api/v1/ingest",
            files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
            headers=admin_headers,
        )
        assert resp.status_code == 200, f"call {i} unexpectedly failed: {resp.text}"

    over_limit = client.post(
        "/api/v1/ingest",
        files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
        headers=admin_headers,
    )
    assert over_limit.status_code == 429


def test_rate_limit_is_per_user(client, user_headers, admin_headers, user_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "greetings", "confidence": 0.99, "guardrail_events": []},
    )
    grant = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert grant.status_code == 200

    for _ in range(config.CHAT_RATE_LIMIT):
        client.post("/api/v1/chat", json={"question": "hello there"}, headers=user_headers)

    # A different user (admin) is not affected by the first user's exhausted limit.
    admin_resp = client.post("/api/v1/chat", json={"question": "hello there"}, headers=admin_headers)
    assert admin_resp.status_code == 200
