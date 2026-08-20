import mongomock

import app.utils.retrieve as retrieve_module
from app.core import guardrail_config
from app.utils.retrieve import route_documents_node


def _client_with_chunks(chunks):
    '''route_documents_node/get_document_bm25_retriever build routing candidates
    straight from document_chunks (see get_document_bm25_retriever's docstring for
    why - NOT from the documents/upload-catalog collection, whose `filename` doesn't
    match chunks' `source`), so tests seed document_chunks directly, same pattern as
    test_retrieval_isolation.py.'''
    client = mongomock.MongoClient(tz_aware=True)
    if chunks:
        collection = client[retrieve_module.DB_NAME][retrieve_module.DOCUMENT_CHUNKS_COLLECTION]
        collection.insert_many(chunks)
    return client


def _chunk(user_id, source, text):
    return {"user_id": user_id, "source": source, "text": text, "page": 0, "sheet_name": "", "content_type": "pdf_text"}


def _route(monkeypatch, chunks, question):
    retrieve_module._document_bm25_retrievers.clear()
    monkeypatch.setattr(retrieve_module, "get_mongo_client", lambda: _client_with_chunks(chunks))
    return route_documents_node({"user_id": "u1", "question": question, "request_id": None})


def test_routes_to_the_document_that_matches(monkeypatch):
    chunks = [
        _chunk("u1", "budget.xlsx", "Quarterly budget report. Marketing spend and total budget allocation for Q3."),
        _chunk("u1", "handbook.pdf", "Employee handbook covering vacation policy and sick leave guidelines."),
    ]
    result = _route(monkeypatch, chunks, "What is the vacation policy?")

    assert result["routed_sources"] == ["handbook.pdf"]
    event = result["guardrail_events"][0]
    assert event["stage"] == "document_routing"
    assert event["passed"] is True  # routing never blocks
    assert event["routing_method"] == "lexical"


def test_routes_to_multiple_documents_for_a_cross_document_question(monkeypatch):
    chunks = [
        _chunk("u1", "budget.xlsx", "Quarterly budget report. Marketing spend and total budget allocation."),
        _chunk("u1", "handbook.pdf", "Employee handbook covering vacation policy and sick leave guidelines."),
    ]
    result = _route(monkeypatch, chunks, "compare the budget report to the vacation policy")

    assert sorted(result["routed_sources"]) == ["budget.xlsx", "handbook.pdf"]


def test_falls_back_to_unrouted_on_a_vague_question(monkeypatch):
    chunks = [
        _chunk("u1", "budget.xlsx", "Quarterly budget report. Marketing spend and total budget allocation."),
        _chunk("u1", "handbook.pdf", "Employee handbook covering vacation policy and sick leave guidelines."),
    ]
    result = _route(monkeypatch, chunks, "hello there")

    assert result["routed_sources"] == []
    assert result["guardrail_events"][0]["routing_method"] == "unrouted"


def test_single_document_user_skips_routing_entirely(monkeypatch):
    chunks = [_chunk("u1", "only.pdf", "Anything at all.")]
    result = _route(monkeypatch, chunks, "completely unrelated question")

    assert result["routed_sources"] == []
    assert result["guardrail_events"][0]["routing_method"] == "single_document"


def test_zero_documents_does_not_error(monkeypatch):
    result = _route(monkeypatch, [], "anything")

    assert result["routed_sources"] == []
    assert result["guardrail_events"][0]["routing_method"] == "no_documents"


def test_disabled_via_config_skips_routing(monkeypatch):
    chunks = [
        _chunk("u1", "budget.xlsx", "Quarterly budget report. Marketing spend and total budget allocation."),
        _chunk("u1", "handbook.pdf", "Employee handbook covering vacation policy and sick leave guidelines."),
    ]
    # Sets the in-process cache directly rather than guardrail_config.update_config(),
    # which persists to Mongo via app.utils.mongo (a different client than the one
    # monkeypatched here for retrieve.py's own Mongo access).
    guardrail_config._cache["document_routing_enabled"] = False
    result = _route(monkeypatch, chunks, "What is the vacation policy?")

    assert result["routed_sources"] == []
    assert result["guardrail_events"][0]["routing_method"] == "disabled"


def test_routing_never_sets_passed_false(monkeypatch):
    '''Routing is a precision optimization, not a guardrail - it must never block a
    turn, even when it finds nothing confident to route to.'''
    chunks = [
        _chunk("u1", "a.pdf", "Something about apples."),
        _chunk("u1", "b.pdf", "Something about oranges."),
    ]
    result = _route(monkeypatch, chunks, "tell me about spacecraft engines")

    assert result["guardrail_events"][0]["passed"] is True


def test_multiple_chunks_from_the_same_source_are_combined(monkeypatch):
    '''A document is many chunks sharing one `source` - routing must score the whole
    document's content, not just whichever chunk happened to be read first.'''
    chunks = [
        _chunk("u1", "handbook.pdf", "Chapter 1: introduction and onboarding."),
        _chunk("u1", "handbook.pdf", "Chapter 2: vacation policy and sick leave."),
        _chunk("u1", "budget.xlsx", "Quarterly budget report. Marketing spend."),
    ]
    result = _route(monkeypatch, chunks, "What is the vacation policy?")

    assert result["routed_sources"] == ["handbook.pdf"]
