from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core.semantic_cache import find_cache_match
from tests.conftest import parse_sse_response, seed_document, signup


def _patch_embed_query(monkeypatch, fn):
    '''embedding_model is a pydantic BaseModel instance (HuggingFaceEmbeddings) - pydantic
    rejects setting attributes that aren't declared model fields, so the method has to be
    patched on the class, not the instance. Reverted automatically by monkeypatch/pytest.'''
    monkeypatch.setattr(HuggingFaceEmbeddings, "embed_query", fn)


class _FakeEmbedder:
    '''Deterministic stand-in: buckets text into one of two directions so cosine similarity
    is exactly 1.0 within a bucket and 0.0 across buckets - no real model needed for the
    matching-logic unit tests.'''

    def embed_query(self, text):
        return [1.0, 0.0] if "warranty" in text.lower() else [0.0, 1.0]


def _fake_candidate(**overrides):
    base = {
        "_id": "msg-1",
        "question": "what is the warranty period",
        "content": "The warranty lasts 12 months.",
        "question_embedding": [1.0, 0.0],
        "logs": ["some log"],
        "graph_response": {"answer": "The warranty lasts 12 months."},
    }
    base.update(overrides)
    return base


def test_find_cache_match_hit(monkeypatch):
    monkeypatch.setattr(
        "app.core.semantic_cache.list_cache_candidates",
        lambda user_id, limit: [_fake_candidate()],
    )

    match, embedding = find_cache_match("user-1", "how long is the warranty on this product", _FakeEmbedder())

    assert match is not None
    assert match["answer"] == "The warranty lasts 12 months."
    assert match["similarity"] > 0.9
    assert embedding == [1.0, 0.0]


def test_find_cache_match_below_threshold_is_a_miss(monkeypatch):
    monkeypatch.setattr(
        "app.core.semantic_cache.list_cache_candidates",
        lambda user_id, limit: [_fake_candidate()],
    )

    match, embedding = find_cache_match("user-1", "how do I install this device", _FakeEmbedder())

    assert match is None
    assert embedding == [0.0, 1.0]  # still returned, so a fresh answer can be stored for next time


def test_find_cache_match_no_candidates_is_a_miss(monkeypatch):
    monkeypatch.setattr("app.core.semantic_cache.list_cache_candidates", lambda *a, **k: [])

    match, embedding = find_cache_match("user-1", "anything at all", _FakeEmbedder())

    assert match is None
    assert embedding == [0.0, 1.0]


class _ConstantEmbedder:
    '''Always returns the same vector - isolates the named-entity guard from cosine
    similarity by making every question look identical to the embedding model.'''

    def embed_query(self, text):
        return [1.0, 0.0]


def test_find_cache_match_blocked_when_named_entity_differs(monkeypatch):
    # Regression test: "Give me the summary of Denice Harris resume" previously matched a
    # cached "Give me the summary of Ghiridhar's resume" answer at ~0.94 cosine similarity,
    # serving the wrong person's resume summary.
    monkeypatch.setattr(
        "app.core.semantic_cache.list_cache_candidates",
        lambda user_id, limit: [_fake_candidate(question="Give me the summary of Ghiridhar's resume")],
    )

    match, _ = find_cache_match("user-1", "Give me the summary of Denice Harris resume", _ConstantEmbedder())

    assert match is None


def test_find_cache_match_allowed_when_named_entity_matches(monkeypatch):
    monkeypatch.setattr(
        "app.core.semantic_cache.list_cache_candidates",
        lambda user_id, limit: [_fake_candidate(question="Give me the summary of Denice Harris resume")],
    )

    match, _ = find_cache_match("user-1", "Summarize Denice Harris resume for me", _ConstantEmbedder())

    assert match is not None


def test_find_cache_match_allowed_when_neither_question_names_an_entity(monkeypatch):
    monkeypatch.setattr(
        "app.core.semantic_cache.list_cache_candidates",
        lambda user_id, limit: [_fake_candidate(question="what is the warranty period")],
    )

    match, _ = find_cache_match("user-1", "how long is the warranty", _ConstantEmbedder())

    assert match is not None


def _grant_ragchatbot(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def _fake_graph_invoke_counter():
    call_count = {"n": 0}

    def fake_invoke(state):
        call_count["n"] += 1
        return {
            "answer": "The warranty lasts 12 months.",
            "retrieved_chunks": [],
            "reranked_chunks": [],
            "context": "warranty context",
            "logs": ["fake graph run"],
            "guardrail_events": [],
            "blocked": False,
            "token_count": 0,
        }

    return call_count, fake_invoke


def test_semantic_cache_hit_skips_the_expensive_pipeline(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    call_count, fake_invoke = _fake_graph_invoke_counter()
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)
    _patch_embed_query(monkeypatch, lambda self, text: [1.0, 0.0])
    seed_document(admin_id)

    first = client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=admin_headers)
    assert first.status_code == 200
    assert call_count["n"] == 1
    first_body = parse_sse_response(first)
    first_cache_event = next(e for e in first_body["graph_response"]["guardrail_events"] if e["stage"] == "semantic_cache")
    assert first_cache_event["cache_hit"] is False

    second = client.post("/api/v1/chat", json={"question": "how long is the warranty"}, headers=admin_headers)
    assert second.status_code == 200
    assert call_count["n"] == 1  # not incremented - the retrieval/generation pipeline was never invoked
    second_body = parse_sse_response(second)
    assert second_body["message"] == "Chat completed successfully (cached)"
    assert second_body["answer"] == "The warranty lasts 12 months."
    second_cache_event = next(e for e in second_body["graph_response"]["guardrail_events"] if e["stage"] == "semantic_cache")
    assert second_cache_event["cache_hit"] is True
    assert second_cache_event["similarity"] > 0.9
    assert second_cache_event["matched_question"] == "what is the warranty period"


def test_semantic_cache_never_reused_across_users(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    call_count, fake_invoke = _fake_graph_invoke_counter()
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)
    _patch_embed_query(monkeypatch, lambda self, text: [1.0, 0.0])

    alice = signup(client, "alice-cache@example.com")
    bob = signup(client, "bob-cache@example.com")
    _grant_ragchatbot(client, admin_headers, alice["user"]["id"])
    _grant_ragchatbot(client, admin_headers, bob["user"]["id"])
    seed_document(alice["user"]["id"])
    seed_document(bob["user"]["id"])

    alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

    client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=alice_headers)
    assert call_count["n"] == 1

    # Identical embedding, but Bob has no history of his own - never reuses Alice's answer.
    resp = client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=bob_headers)
    assert call_count["n"] == 2
    cache_event = next(e for e in parse_sse_response(resp)["graph_response"]["guardrail_events"] if e["stage"] == "semantic_cache")
    assert cache_event["cache_hit"] is False


def test_blocked_answers_never_become_cache_candidates(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    call_count, fake_invoke = _fake_graph_invoke_counter()

    def fake_invoke_blocked(state):
        call_count["n"] += 1
        return {
            "answer": "I don't know based on the provided context.",
            "retrieved_chunks": [], "reranked_chunks": [], "context": "",
            "logs": ["blocked"], "guardrail_events": [], "blocked": True, "token_count": 0,
        }

    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke_blocked)
    _patch_embed_query(monkeypatch, lambda self, text: [1.0, 0.0])
    seed_document(admin_id)

    client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=admin_headers)
    assert call_count["n"] == 1

    # A second, identical-embedding question must NOT hit the (blocked, never-cached) first answer.
    resp = client.post("/api/v1/chat", json={"question": "what is the warranty period"}, headers=admin_headers)
    assert call_count["n"] == 2
    cache_event = next(e for e in parse_sse_response(resp)["graph_response"]["guardrail_events"] if e["stage"] == "semantic_cache")
    assert cache_event["cache_hit"] is False
