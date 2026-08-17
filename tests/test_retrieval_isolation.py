'''Retrieval must only ever draw from the requesting user's own ingested chunks -
never another user's, and never a shared/global pool, even for an admin.

get_vectorstore()'s dense search relies on a real Atlas $vectorSearch pre_filter,
which mongomock can't emulate, so that half is covered by code review + the
pre_filter kwarg check below rather than a behavioral test. BM25 is a pure
in-memory index built from whatever documents get_bm25_retriever queries for, so
its per-user scoping is fully testable against mongomock.
'''

import mongomock

import app.utils.retrieve as retrieve_module
from tests.conftest import seed_document


def _seeded_client():
    client = mongomock.MongoClient(tz_aware=True)
    collection = client[retrieve_module.DB_NAME][retrieve_module.DOCUMENT_CHUNKS_COLLECTION]
    collection.insert_many([
        {"text": "Alice's warranty is 12 months.", "source": "alice.pdf", "page": 1, "sheet_name": "", "content_type": "pdf_text", "user_id": "alice"},
        {"text": "Alice's return policy is 30 days.", "source": "alice.pdf", "page": 2, "sheet_name": "", "content_type": "pdf_text", "user_id": "alice"},
        {"text": "Bob's warranty is 24 months.", "source": "bob.pdf", "page": 1, "sheet_name": "", "content_type": "pdf_text", "user_id": "bob"},
    ])
    return client


def test_bm25_retriever_only_sees_the_requesting_users_own_chunks(monkeypatch):
    retrieve_module._bm25_retrievers.clear()
    monkeypatch.setattr(retrieve_module, "get_mongo_client", lambda: _seeded_client())

    alice_retriever = retrieve_module.get_bm25_retriever("alice")
    alice_texts = {d.page_content for d in alice_retriever.invoke("warranty")}
    assert "Alice's warranty is 12 months." in alice_texts
    assert "Bob's warranty is 24 months." not in alice_texts

    bob_retriever = retrieve_module.get_bm25_retriever("bob")
    bob_texts = {d.page_content for d in bob_retriever.invoke("warranty")}
    assert "Bob's warranty is 24 months." in bob_texts
    assert "Alice's warranty is 12 months." not in bob_texts


def test_bm25_retriever_is_none_for_a_user_with_no_documents(monkeypatch):
    retrieve_module._bm25_retrievers.clear()
    monkeypatch.setattr(retrieve_module, "get_mongo_client", lambda: _seeded_client())

    assert retrieve_module.get_bm25_retriever("nobody") is None


def test_admin_gets_no_special_bm25_visibility(monkeypatch):
    '''An "admin" user_id has no special case anywhere in get_bm25_retriever - it's
    filtered by user_id like anyone else, so an admin with no uploads of their own
    sees nothing, not everyone's chunks.'''
    retrieve_module._bm25_retrievers.clear()
    monkeypatch.setattr(retrieve_module, "get_mongo_client", lambda: _seeded_client())

    assert retrieve_module.get_bm25_retriever("admin-user-id") is None


def test_invalidate_bm25_cache_forces_a_rebuild(monkeypatch):
    retrieve_module._bm25_retrievers.clear()
    client = _seeded_client()
    monkeypatch.setattr(retrieve_module, "get_mongo_client", lambda: client)

    assert retrieve_module.get_bm25_retriever("carol") is None  # cached as None

    collection = client[retrieve_module.DB_NAME][retrieve_module.DOCUMENT_CHUNKS_COLLECTION]
    collection.insert_one(
        {"text": "Carol's manual explains setup.", "source": "carol.pdf", "page": 1, "sheet_name": "", "content_type": "pdf_text", "user_id": "carol"}
    )

    assert retrieve_module.get_bm25_retriever("carol") is None  # still cached (stale)

    retrieve_module.invalidate_bm25_cache("carol")
    carol_retriever = retrieve_module.get_bm25_retriever("carol")
    assert carol_retriever is not None
    assert "Carol's manual explains setup." in {d.page_content for d in carol_retriever.invoke("manual")}


def test_dense_search_is_prefiltered_by_user_id():
    import inspect
    sig = inspect.signature(retrieve_module.retrieve_node)
    source = inspect.getsource(retrieve_module.retrieve_node)
    assert 'pre_filter={"user_id": {"$eq": user_id}}' in source


def test_chat_ignores_client_supplied_user_id(client, admin_headers, monkeypatch):
    '''A client can't spoof another user's id through the request body to read their
    documents - the server overwrites it from the authenticated session.'''
    monkeypatch.setattr(
        "app.api.v1.api.IntentClassifier.classify_intent",
        lambda self, question, model=None: {"intent": "question", "confidence": 0.99, "guardrail_events": []},
    )
    captured_state = {}

    def fake_invoke(state):
        captured_state["user_id"] = state.user_id
        return {
            "answer": "ok", "retrieved_chunks": [], "reranked_chunks": [], "context": "",
            "logs": ["fake"], "guardrail_events": [], "blocked": False, "token_count": 0,
        }

    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", fake_invoke)

    admin_id = client.get("/api/v1/auth/me", headers=admin_headers).json()["id"]
    seed_document(admin_id)
    resp = client.post(
        "/api/v1/chat",
        json={"question": "what is the warranty period", "user_id": "someone-elses-id"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert captured_state["user_id"] == admin_id
    assert captured_state["user_id"] != "someone-elses-id"
