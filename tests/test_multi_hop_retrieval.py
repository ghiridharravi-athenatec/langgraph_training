'''Multi-hop retrieval (app/utils/retrieve.py's reformulate_query_node/_route_on_retry) -
the Document Agent's own genuinely agentic step: on a self-reported decline, it can
autonomously rewrite the search query and retry, capped by config.RAG_MAX_RETRIEVAL_HOPS.
Every guardrail stage in the loop (retrieval validation, injection filtering,
groundedness, output validation) still runs exactly as before on every hop - looping
only changes how many retrieval attempts happen, never whether a check runs.
'''

from app.core import config
from app.core.llm_provider import LLMResult
from app.utils.retrieve import NO_ANSWER_IN_CONTEXT_TEXT, _route_on_retry


def test_route_on_retry_stops_when_not_declined():
    assert _route_on_retry({"declined": False, "retrieval_hop": 0}) == "done"


def test_route_on_retry_retries_on_decline_under_the_cap():
    assert _route_on_retry({"declined": True, "retrieval_hop": 0}) == "retry"


def test_route_on_retry_stops_at_the_hop_cap_even_if_still_declined():
    max_hop_reached = config.RAG_MAX_RETRIEVAL_HOPS - 1
    assert _route_on_retry({"declined": True, "retrieval_hop": max_hop_reached}) == "done"


def test_route_on_retry_defaults_hop_to_zero():
    # No retrieval_hop key at all (first pass) - treated as hop 0, same as an explicit 0.
    assert _route_on_retry({"declined": True}) == "retry"


def test_reformulate_query_node_rewrites_the_search_query(monkeypatch):
    from app.core.llm_provider import LLMResult
    from app.utils import retrieve as retrieve_module

    def _fake_generate_json(prompt, max_tokens, stage, model=None):
        return LLMResult(
            text='{"search_query": "broader search terms"}', token_count=15, provider="claude",
            safety_event={"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"},
            log="fake",
        )

    monkeypatch.setattr(retrieve_module.llm_provider, "generate_json", _fake_generate_json)

    result = retrieve_module.reformulate_query_node({"question": "what is the warranty period", "request_id": None, "retrieval_hop": 0})
    assert result["search_query"] == "broader search terms"
    assert result["retrieval_hop"] == 1


def test_reformulate_query_node_falls_back_to_original_question_on_malformed_response(monkeypatch):
    from app.core.llm_provider import LLMResult
    from app.utils import retrieve as retrieve_module

    def _fake_generate_json(prompt, max_tokens, stage, model=None):
        return LLMResult(
            text="not valid json", token_count=15, provider="claude",
            safety_event={"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"},
            log="fake",
        )

    monkeypatch.setattr(retrieve_module.llm_provider, "generate_json", _fake_generate_json)

    result = retrieve_module.reformulate_query_node({"question": "what is the warranty period", "request_id": None, "retrieval_hop": 0})
    assert result["search_query"] == "what is the warranty period"
    assert result["retrieval_hop"] == 1


def test_retrieve_node_uses_search_query_when_present(monkeypatch):
    from app.utils import retrieve as retrieve_module

    captured = {}

    class _FakeVectorstore:
        def similarity_search_with_score(self, query, k, pre_filter):
            captured["query"] = query
            return []

    monkeypatch.setattr(retrieve_module, "get_vectorstore", lambda: _FakeVectorstore())
    monkeypatch.setattr(retrieve_module, "get_bm25_retriever", lambda user_id, sources=None: None)

    retrieve_module.retrieve_node({
        "question": "original question", "search_query": "reformulated query",
        "user_id": "u1", "request_id": None, "retrieval_hop": 1,
    })
    assert captured["query"] == "reformulated query"


def test_retrieve_node_falls_back_to_question_when_no_search_query(monkeypatch):
    from app.utils import retrieve as retrieve_module

    captured = {}

    class _FakeVectorstore:
        def similarity_search_with_score(self, query, k, pre_filter):
            captured["query"] = query
            return []

    monkeypatch.setattr(retrieve_module, "get_vectorstore", lambda: _FakeVectorstore())
    monkeypatch.setattr(retrieve_module, "get_bm25_retriever", lambda user_id, sources=None: None)

    retrieve_module.retrieve_node({"question": "original question", "user_id": "u1", "request_id": None})
    assert captured["query"] == "original question"


def test_validate_output_node_flags_declined_only_on_the_success_path(monkeypatch):
    from app.utils import retrieve as retrieve_module

    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "check_output",
        lambda answer: {"stage": "output_validation", "passed": True, "sanitized_answer": answer, "reason": None, "checks": []},
    )

    result = retrieve_module.validate_output_node({"answer": NO_ANSWER_IN_CONTEXT_TEXT, "context": "some context", "request_id": None})
    assert result["declined"] is True


def test_validate_output_node_never_flags_declined_when_output_validation_blocks(monkeypatch):
    from app.utils import retrieve as retrieve_module

    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "check_output",
        lambda answer: {"stage": "output_validation", "passed": False, "sanitized_answer": None, "reason": "blocked keyword", "checks": []},
    )

    result = retrieve_module.validate_output_node({"answer": NO_ANSWER_IN_CONTEXT_TEXT, "context": "some context", "request_id": None})
    assert result["declined"] is False


def _stub_out_retrieval_and_guardrails(monkeypatch, answers_by_hop):
    '''Shared setup for the two real-graph tests below - mocks only the pieces that
    need a real network/model call (vector search, BM25, injection screening,
    answer generation, groundedness, reformulation), leaving every guardrail node's
    own real pass/fail logic (validate_retrieval_node, validate_output_node,
    _route_on_retry) genuinely exercised. answers_by_hop maps hop index -> the answer
    answer_node should "generate" on that pass, so a test can make hop 0 decline and
    hop 1 succeed.'''
    from app.utils import retrieve as retrieve_module

    class _FakeVectorstore:
        def similarity_search_with_score(self, query, k, pre_filter):
            return []  # BM25 alone still produces a chunk below, via get_bm25_retriever

    class _FakeDoc:
        def __init__(self):
            self.page_content = "some chunk content"
            self.metadata = {"source": "doc.pdf", "content_type": "pdf"}

    monkeypatch.setattr(retrieve_module, "get_vectorstore", lambda: _FakeVectorstore())
    # route_documents_node's own (separate) BM25 index, used only to decide which
    # document(s) to scope retrieval to - None means "no ingested documents to route
    # to", so it searches the whole (fake, mocked-below) corpus, same as before this
    # node existed. Avoids needing a real Mongo connection for this test.
    monkeypatch.setattr(retrieve_module, "get_document_bm25_retriever", lambda user_id: None)

    class _FakeBM25:
        def invoke(self, query):
            return [_FakeDoc()]

    monkeypatch.setattr(retrieve_module, "get_bm25_retriever", lambda user_id, sources=None: _FakeBM25())
    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "check_retrieval",
        lambda chunks: {"stage": "retrieval_validation", "passed": True, "reason": None, "filtered_chunks": chunks},
    )
    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "screen_chunks_for_injection",
        lambda chunks: (chunks, {"stage": "context_injection_filter", "passed": True, "reason": None, "excluded_count": 0}),
    )
    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "check_groundedness",
        lambda answer, context, embedding_model: {"stage": "groundedness_check", "passed": True, "reason": None, "score": 0.9},
    )
    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "check_output",
        lambda answer: {"stage": "output_validation", "passed": True, "sanitized_answer": answer, "reason": None, "checks": []},
    )

    hop_counter = {"n": 0}

    def _fake_llm_invoke(prompt, model=None):
        hop = hop_counter["n"]
        hop_counter["n"] += 1
        return {"answer": answers_by_hop[hop], "guardrail_events": [], "token_count": 5, "logs": []}

    monkeypatch.setattr(retrieve_module, "llm_invoke", _fake_llm_invoke)

    def _fake_generate_json(prompt, max_tokens, stage, model=None):
        assert stage == "query_reformulation"
        return LLMResult(
            text='{"search_query": "a different search"}', token_count=5, provider="claude",
            safety_event={"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"}, log="fake",
        )

    monkeypatch.setattr(retrieve_module.llm_provider, "generate_json", _fake_generate_json)
    return hop_counter


def test_real_graph_retries_once_and_succeeds_on_the_second_hop(monkeypatch):
    '''The genuine end-to-end proof: run the REAL compiled graph (not mocked out),
    with hop 0 declining and hop 1 succeeding - confirms reformulate_query_node,
    _route_on_retry, and the retrieve->...->validate_output->reformulate->retrieve
    loop edge all actually work together, not just in isolation.'''
    from app.utils import retrieve as retrieve_module

    hop_counter = _stub_out_retrieval_and_guardrails(
        monkeypatch, {0: NO_ANSWER_IN_CONTEXT_TEXT, 1: "The warranty lasts 12 months."},
    )

    state = {
        "user_id": "u1", "question": "what is the warranty period", "model": None, "request_id": None,
        "history": [], "routed_sources": [], "tier3_skip": [],
    }
    result = retrieve_module.compiled_graph.invoke(state)

    assert result["answer"] == "The warranty lasts 12 months."
    assert result["retrieval_hop"] == 1
    assert hop_counter["n"] == 2  # exactly two answer_node calls - one per hop, no more


def test_real_graph_stops_at_the_hop_cap_when_still_declining(monkeypatch):
    '''Every hop declines - the loop must still terminate at config.RAG_MAX_RETRIEVAL_HOPS
    rather than looping forever, and the final answer is the (correct) decline text.'''
    from app.utils import retrieve as retrieve_module

    # Every hop returns the decline text - answers_by_hop needs an entry for however
    # many hops the cap actually allows.
    answers_by_hop = {i: NO_ANSWER_IN_CONTEXT_TEXT for i in range(config.RAG_MAX_RETRIEVAL_HOPS + 1)}
    hop_counter = _stub_out_retrieval_and_guardrails(monkeypatch, answers_by_hop)

    state = {
        "user_id": "u1", "question": "what is the warranty period", "model": None, "request_id": None,
        "history": [], "routed_sources": [], "tier3_skip": [],
    }
    result = retrieve_module.compiled_graph.invoke(state)

    assert result["answer"] == NO_ANSWER_IN_CONTEXT_TEXT
    assert hop_counter["n"] == config.RAG_MAX_RETRIEVAL_HOPS  # never exceeds the cap
