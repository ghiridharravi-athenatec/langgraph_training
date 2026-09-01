'''ragchatbot only ever answers from documents, so it has no route to decide - the
one thing left for a bounded model decision to own is Tier 3: whether the optional
bias_detection check (app/core/orchestrator.py's TIER3_ALLOWLIST) is worth running for
a given question. Unlike the Assistant project's routing decision, this one is
piggybacked onto the intent-classification call ragchatbot already makes for every
question (IntentClassifier.classify_intent in app/utils/llm.py) rather than a
standalone LLM call - these tests confirm that piggybacking actually works end to end,
that a non-allowlisted skip request is dropped, and that a blocked request never even
reaches classification.
'''

from app.core.llm_provider import LLMResult
from app.core.orchestrator import interpret_tier3_decision, tier3_decision_fragments
from tests.conftest import parse_sse_response, seed_document


def _safety_event(stage="model_input_validation"):
    return {"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"}


def _fake_generate_json(payload_json: str, token_count: int = 10):
    def _fake(prompt, max_tokens, stage, model=None):
        return LLMResult(text=payload_json, token_count=token_count, provider="claude", safety_event=_safety_event(), log="fake")
    return _fake


def _fake_invoke(state):
    return {
        "answer": "doc answer", "retrieved_chunks": [], "reranked_chunks": [], "context": "",
        "logs": ["fake"], "guardrail_events": [], "blocked": False, "token_count": 5,
    }


# ---------------------------------------------------------------------------
# tier3_decision_fragments / interpret_tier3_decision - pure functions.
# ---------------------------------------------------------------------------

def test_tier3_decision_fragments_returns_non_empty_instructions_and_schema():
    instructions, schema_fields = tier3_decision_fragments()
    assert "bias_detection" in instructions
    assert "tier3_skip" in schema_fields


def test_interpret_tier3_decision_accepts_an_allowlisted_skip():
    assert interpret_tier3_decision({"tier3_skip": ["bias_detection"]}) == ["bias_detection"]


def test_interpret_tier3_decision_drops_non_allowlisted_values():
    assert interpret_tier3_decision({"tier3_skip": ["bias_detection", "output_validation", "quota_check"]}) == ["bias_detection"]


def test_interpret_tier3_decision_defaults_to_empty():
    assert interpret_tier3_decision({}) == []
    assert interpret_tier3_decision({"tier3_skip": []}) == []


# ---------------------------------------------------------------------------
# End-to-end through /chat - piggybacked on the classification call, not a
# standalone orchestrator round-trip.
# ---------------------------------------------------------------------------

def test_chat_applies_a_requested_bias_detection_skip(client, admin_headers, admin_id, monkeypatch):
    seed_document(admin_id)
    monkeypatch.setattr(
        "app.utils.llm.llm_provider.generate_json",
        _fake_generate_json('{"intent": "question", "confidence": 0.99, "tier3_skip": ["bias_detection"]}'),
    )

    def _fail_if_called():
        raise AssertionError("bias_guardrail_fragments should not be called once bias_detection was skipped")

    monkeypatch.setattr("app.utils.retrieve.guardrails_agent.bias_guardrail_fragments", _fail_if_called)
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", _fake_invoke)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say about setup"}, headers=admin_headers)
    assert resp.status_code == 200
    events = parse_sse_response(resp)["graph_response"]["guardrail_events"]
    tier3_event = next(e for e in events if e["stage"] == "tier3_skip_decision")
    assert tier3_event["tier3_skip"] == ["bias_detection"]
    assert tier3_event["passed"] is True


def test_chat_runs_bias_detection_by_default(client, admin_headers, admin_id, monkeypatch):
    '''Trace-level check that the default (no skip requested) case reports an empty
    tier3_skip - answer_node's actual gating on state["tier3_skip"] (app/utils/retrieve.py)
    is exercised separately below via a direct unit test, since mocking out
    compiled_graph.invoke entirely (as the other tests here do) bypasses answer_node.'''
    seed_document(admin_id)
    monkeypatch.setattr(
        "app.utils.llm.llm_provider.generate_json",
        _fake_generate_json('{"intent": "question", "confidence": 0.99}'),
    )
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", _fake_invoke)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say about setup"}, headers=admin_headers)
    assert resp.status_code == 200
    events = parse_sse_response(resp)["graph_response"]["guardrail_events"]
    tier3_event = next(e for e in events if e["stage"] == "tier3_skip_decision")
    assert tier3_event["tier3_skip"] == []


def test_answer_node_skips_bias_fragments_only_when_requested(monkeypatch):
    '''Direct unit test of the gating this change adds to answer_node (app/utils/retrieve.py) -
    the /chat integration tests above mock out compiled_graph.invoke entirely (following
    this test file's other cases), which bypasses answer_node, so this exercises it
    directly instead.'''
    import app.utils.retrieve as retrieve_module

    calls = []
    monkeypatch.setattr(
        retrieve_module.guardrails_agent, "bias_guardrail_fragments", lambda: (calls.append(True), ("bias instructions", "bias schema fields"))[1]
    )

    def _fake_llm_invoke(prompt, model=None):
        return {"answer": "ok", "guardrail_events": [], "token_count": 0, "logs": []}

    monkeypatch.setattr(retrieve_module, "llm_invoke", _fake_llm_invoke)

    base_state = {
        "request_id": None, "history": [], "reranked_chunks": [], "question": "q",
        "model": None, "context": "", "logs": [], "guardrail_events": [], "token_count": 0,
    }

    retrieve_module.answer_node({**base_state, "tier3_skip": ["bias_detection"]})
    assert calls == []

    retrieve_module.answer_node({**base_state, "tier3_skip": []})
    assert calls == [True]


def test_chat_drops_a_non_allowlisted_skip_request(client, admin_headers, admin_id, monkeypatch):
    seed_document(admin_id)
    monkeypatch.setattr(
        "app.utils.llm.llm_provider.generate_json",
        _fake_generate_json('{"intent": "question", "confidence": 0.99, "tier3_skip": ["output_validation"]}'),
    )
    monkeypatch.setattr("app.api.v1.api.compiled_graph.invoke", _fake_invoke)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say about setup"}, headers=admin_headers)
    assert resp.status_code == 200
    events = parse_sse_response(resp)["graph_response"]["guardrail_events"]
    tier3_event = next(e for e in events if e["stage"] == "tier3_skip_decision")
    assert tier3_event["tier3_skip"] == []


def test_chat_blocked_by_input_validation_never_reaches_classification(client, admin_headers, monkeypatch):
    '''Input validation now runs once at the top of _generate_chat_response (Tier 1,
    before the Supervisor's own routing decision even exists) - a block here returns a
    flat response, never reaching document_chat's own classification call at all.'''
    def _fail_if_called(*a, **kw):
        raise AssertionError("the classification call should never run once input validation has already blocked")

    monkeypatch.setattr("app.utils.llm.llm_provider.generate_json", _fail_if_called)
    resp = client.post("/api/v1/chat", json={"question": "a"}, headers=admin_headers)
    assert resp.status_code == 200
    events = parse_sse_response(resp)["guardrail_events"]
    assert next(e for e in events if e["stage"] == "input_validation")["passed"] is False
    assert not any(e["stage"] == "tier3_skip_decision" for e in events)
