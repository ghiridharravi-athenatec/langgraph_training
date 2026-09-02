'''The Supervisor/Orchestrator (app/core/orchestrator.py, app/api/v1/api.py's
_generate_chat_response) is the one place in the app where an LLM's own reading of the
prompt genuinely decides what happens next - bounded routing between exactly two
grounded sources (the user's documents, their connected database), never a third
"general knowledge" option. These tests cover the pure-function building blocks and the
integration behaviors not already covered by tests/test_chat_routing.py (dispatch
correctness, single-route skip, and the no-sources block live there instead): fallback
on a malformed routing response, and that Tier 1 blocks before the routing call is ever
reached.
'''

from app.core.llm_provider import LLMResult
from app.core.orchestrator import (
    ALL_ROUTES,
    filter_routes_by_permission,
    interpret_orchestrator_decision,
    resolve_database_connection,
)
from app.utils.retrieve import NO_ANSWER_IN_CONTEXT_TEXT
from tests.conftest import parse_sse_response, seed_document


def _safety_event(stage="orchestrator_routing"):
    return {"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"}


def _fake_generate_json(payload_json: str, token_count: int = 10):
    def _fake(prompt, max_tokens, stage, model=None):
        return LLMResult(text=payload_json, token_count=token_count, provider="claude", safety_event=_safety_event(), log="fake")
    return _fake


def _grant(client, admin_headers, user_id, *projects):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions", json={"projects": list(projects)}, headers=admin_headers,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# filter_routes_by_permission / resolve_database_connection - pure functions,
# no HTTP needed, just the client fixture's mongomock patch active.
# ---------------------------------------------------------------------------

def test_all_routes_never_includes_general_knowledge():
    assert set(ALL_ROUTES) == {"document_chat", "database_chat"}


def test_filter_routes_by_permission_admin_gets_both(client, admin_headers):
    admin = client.get("/api/v1/auth/me", headers=admin_headers).json()
    admin["_id"] = admin["id"]
    assert set(filter_routes_by_permission(admin)) == {"document_chat", "database_chat"}


def test_filter_routes_by_permission_user_with_one_grant(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, "ragchatbot")
    user = client.get("/api/v1/auth/me", headers=user_headers).json()
    user["_id"] = user["id"]
    assert filter_routes_by_permission(user) == ["document_chat"]


def test_filter_routes_by_permission_user_with_no_grants(client, user_headers, user_id):
    user = client.get("/api/v1/auth/me", headers=user_headers).json()
    user["_id"] = user["id"]
    assert filter_routes_by_permission(user) == []


def test_resolve_database_connection_none_when_zero_or_multiple(client, admin_id, monkeypatch):
    assert resolve_database_connection(admin_id) is None

    monkeypatch.setattr(
        "app.core.orchestrator.list_database_connections",
        lambda user_id: [{"_id": "a"}, {"_id": "b"}],
    )
    assert resolve_database_connection(admin_id) is None


def test_resolve_database_connection_returns_the_one_connection(monkeypatch):
    monkeypatch.setattr("app.core.orchestrator.list_database_connections", lambda user_id: [{"_id": "conn-1"}])
    assert resolve_database_connection("someone") == "conn-1"


# ---------------------------------------------------------------------------
# interpret_orchestrator_decision - never trusts raw model output as control flow.
# ---------------------------------------------------------------------------

def test_interpret_orchestrator_decision_accepts_a_valid_route():
    decision = interpret_orchestrator_decision({"route": "database_chat", "reasoning": "about the data"}, ["document_chat", "database_chat"])
    assert decision.route == "database_chat"
    assert decision.fallback_used is False


def test_interpret_orchestrator_decision_falls_back_on_invalid_route():
    decision = interpret_orchestrator_decision({"route": "general_chat"}, ["document_chat", "database_chat"])
    assert decision.route == "document_chat"  # first in fixed priority order
    assert decision.fallback_used is True


def test_interpret_orchestrator_decision_falls_back_on_missing_route():
    decision = interpret_orchestrator_decision({}, ["database_chat"])
    assert decision.route == "database_chat"
    assert decision.fallback_used is True


def test_interpret_orchestrator_decision_accepts_both_when_both_routes_available():
    decision = interpret_orchestrator_decision({"route": "both"}, ["document_chat", "database_chat"])
    assert decision.route == "both"
    assert decision.fallback_used is False


def test_interpret_orchestrator_decision_rejects_both_when_only_one_route_available():
    '''"both" is never fabricated as a fallback target - with only one real route
    available, "both" isn't a valid choice at all, so it's treated exactly like any
    other invalid route: fall back to the one route that is actually available.'''
    decision = interpret_orchestrator_decision({"route": "both"}, ["document_chat"])
    assert decision.route == "document_chat"
    assert decision.fallback_used is True


def test_interpret_orchestrator_decision_accepts_a_valid_model_tier():
    decision = interpret_orchestrator_decision(
        {"route": "document_chat", "model_tier": "opus"}, ["document_chat", "database_chat"],
    )
    assert decision.model_tier == "opus"


def test_interpret_orchestrator_decision_drops_an_invalid_model_tier():
    decision = interpret_orchestrator_decision(
        {"route": "document_chat", "model_tier": "gpt-5"}, ["document_chat", "database_chat"],
    )
    assert decision.model_tier is None


def test_interpret_orchestrator_decision_defaults_model_tier_to_none():
    decision = interpret_orchestrator_decision({"route": "document_chat"}, ["document_chat", "database_chat"])
    assert decision.model_tier is None


# ---------------------------------------------------------------------------
# Integration - fallback and Tier-1 ordering, not already covered by
# tests/test_chat_routing.py's dispatch/single-route-skip/no-sources tests.
# ---------------------------------------------------------------------------

def test_chat_falls_back_on_malformed_routing_response(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    client.post(
        "/api/v1/database/connections",
        json={"name": "MES", "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )
    seed_document(admin_id)

    monkeypatch.setattr("app.api.v1.api.llm_provider.generate_json", _fake_generate_json("not valid json"))

    def _fail_if_called(self, question, model=None, history=None):
        raise AssertionError("document_chat's own intent classification should not run if routing already failed and fell back to it incorrectly without dispatching")

    async def _fake_document_answer(state, current_user, history):
        return {"message": "Chat completed successfully", "answer": "doc answer (fallback)", "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)

    resp = client.post("/api/v1/chat", json={"question": "ambiguous question"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    routing_event = next(e for e in body["graph_response"]["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["fallback_used"] is True
    assert routing_event["route"] == "document_chat"  # first in fixed priority order
    assert body["routed_to"] == "document_chat"
    assert body["answer"] == "doc answer (fallback)"


def test_chat_input_validation_blocks_before_the_routing_call(client, admin_headers, monkeypatch):
    def _fail_if_called(*a, **kw):
        raise AssertionError("the routing LLM call should never run once input validation has already blocked")

    monkeypatch.setattr("app.api.v1.api.llm_provider.generate_json", _fail_if_called)
    resp = client.post("/api/v1/chat", json={"question": "a"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    events = body["guardrail_events"]
    assert next(e for e in events if e["stage"] == "input_validation")["passed"] is False
    assert not any(e["stage"] == "orchestrator_routing" for e in events)


# ---------------------------------------------------------------------------
# Model-tier autonomy - only ever applies when the picker is "auto" AND the
# routing call actually ran (2+ sources) - an explicit pick is never touched.
# ---------------------------------------------------------------------------

def _connect_database(client, admin_headers, name="MES"):
    client.post(
        "/api/v1/database/connections",
        json={"name": name, "engine": "postgresql", "host": "h", "username": "u", "password": "p", "database": "d"},
        headers=admin_headers,
    )


def test_chat_model_tier_override_applies_when_auto(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    monkeypatch.setattr(
        "app.api.v1.api.llm_provider.generate_json",
        _fake_generate_json('{"route": "document_chat", "reasoning": "simple lookup", "model_tier": "haiku"}'),
    )
    captured_model = {}

    async def _fake_document_answer(state, current_user, history):
        captured_model["model"] = state.model
        return {"message": "Chat completed successfully", "answer": "doc answer", "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say", "model": "auto"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    routing_event = next(e for e in body["graph_response"]["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["model_tier"] == "haiku"
    assert captured_model["model"] == "haiku"  # overridden before dispatch


def test_chat_model_tier_never_overrides_an_explicit_pick(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    monkeypatch.setattr(
        "app.api.v1.api.llm_provider.generate_json",
        _fake_generate_json('{"route": "document_chat", "reasoning": "simple lookup", "model_tier": "haiku"}'),
    )
    captured_model = {}

    async def _fake_document_answer(state, current_user, history):
        captured_model["model"] = state.model
        return {"message": "Chat completed successfully", "answer": "doc answer", "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say", "model": "opus"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    routing_event = next(e for e in body["graph_response"]["guardrail_events"] if e["stage"] == "orchestrator_routing")
    # The routing prompt was never even asked for a tier, so the model never
    # returned one - nothing to override with, even if it had tried to.
    assert routing_event["model_tier"] is None
    assert captured_model["model"] == "opus"


# ---------------------------------------------------------------------------
# Multi-source synthesis ("both" route).
# ---------------------------------------------------------------------------

def test_chat_dispatches_both_sources_and_synthesizes(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    calls = []

    async def _fake_document_answer(state, current_user, history):
        calls.append("document")
        return {"message": "Chat completed successfully", "answer": "warranty is 12 months", "blocked": False, "guardrail_events": [], "logs": []}

    def _fake_database_answer(question, connection, current_user, model, history, request_id, show_tier1_progress=True):
        calls.append("database")
        return {"message": "Chat completed successfully", "answer": "stock is 50 units", "blocked": False, "guardrail_events": [], "logs": []}

    def _fake_generate_json_dispatch(prompt, max_tokens, stage, model=None):
        if stage == "orchestrator_routing":
            return LLMResult(text='{"route": "both", "reasoning": "needs both"}', token_count=10, provider="claude", safety_event=_safety_event(stage), log="fake")
        if stage == "answer_synthesis":
            return LLMResult(text='{"answer": "Combined: warranty is 12 months and stock is 50 units"}', token_count=20, provider="claude", safety_event=_safety_event(stage), log="fake")
        raise AssertionError(f"unexpected stage {stage!r}")

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)
    monkeypatch.setattr("app.api.v1.api.generate_database_answer", _fake_database_answer)
    monkeypatch.setattr("app.api.v1.api.llm_provider.generate_json", _fake_generate_json_dispatch)

    resp = client.post("/api/v1/chat", json={"question": "compare doc and database"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert set(calls) == {"document", "database"}
    assert body["answer"] == "Combined: warranty is 12 months and stock is 50 units"
    assert body["routed_to"] == "both"
    routing_event = next(e for e in body["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["route"] == "both"


def test_chat_both_synthesis_falls_back_to_concatenation_on_malformed_response(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    async def _fake_document_answer(state, current_user, history):
        return {"message": "Chat completed successfully", "answer": "doc says X", "blocked": False, "guardrail_events": [], "logs": []}

    def _fake_database_answer(question, connection, current_user, model, history, request_id, show_tier1_progress=True):
        return {"message": "Chat completed successfully", "answer": "db says Y", "blocked": False, "guardrail_events": [], "logs": []}

    def _fake_generate_json_dispatch(prompt, max_tokens, stage, model=None):
        if stage == "orchestrator_routing":
            return LLMResult(text='{"route": "both", "reasoning": "needs both"}', token_count=10, provider="claude", safety_event=_safety_event(stage), log="fake")
        if stage == "answer_synthesis":
            return LLMResult(text="not valid json", token_count=20, provider="claude", safety_event=_safety_event(stage), log="fake")
        raise AssertionError(f"unexpected stage {stage!r}")

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)
    monkeypatch.setattr("app.api.v1.api.generate_database_answer", _fake_database_answer)
    monkeypatch.setattr("app.api.v1.api.llm_provider.generate_json", _fake_generate_json_dispatch)

    resp = client.post("/api/v1/chat", json={"question": "compare doc and database"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert "doc says X" in body["answer"] and "db says Y" in body["answer"]


# ---------------------------------------------------------------------------
# Fallback-on-empty retry.
# ---------------------------------------------------------------------------

def test_chat_falls_back_to_database_when_documents_come_back_ungrounded(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    monkeypatch.setattr(
        "app.api.v1.api.llm_provider.generate_json",
        _fake_generate_json('{"route": "document_chat", "reasoning": "seems doc-related"}'),
    )

    async def _fake_document_answer(state, current_user, history):
        return {"message": "Chat completed successfully", "answer": NO_ANSWER_IN_CONTEXT_TEXT, "blocked": False, "guardrail_events": [], "logs": []}

    def _fake_database_answer(question, connection, current_user, model, history, request_id, show_tier1_progress=True):
        return {"message": "Chat completed successfully", "answer": "There are 3 open work orders.", "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)
    monkeypatch.setattr("app.api.v1.api.generate_database_answer", _fake_database_answer)

    resp = client.post("/api/v1/chat", json={"question": "how many work orders are open"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == "There are 3 open work orders."
    assert body["routed_to"] == "database_chat"
    routing_event = next(e for e in body["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["source_fallback_used"] is True
    assert routing_event["source_fallback_from"] == "document_chat"


def test_chat_no_fallback_when_only_one_source_was_ever_available(client, admin_headers, admin_id, monkeypatch):
    '''Single-route-skip already means there's no "other source" to fall back to -
    an ungrounded answer there is just the final answer, unchanged.'''
    seed_document(admin_id)

    def _fail_if_called(*a, **kw):
        raise AssertionError("no database is connected - a fallback attempt should never be made")

    async def _fake_document_answer(state, current_user, history):
        return {"message": "Chat completed successfully", "answer": NO_ANSWER_IN_CONTEXT_TEXT, "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)
    monkeypatch.setattr("app.api.v1.api.generate_database_answer", _fail_if_called)

    resp = client.post("/api/v1/chat", json={"question": "what does the manual say"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == NO_ANSWER_IN_CONTEXT_TEXT
    assert body["routed_to"] == "document_chat"


def test_chat_persists_original_ungrounded_result_when_fallback_also_ungrounded(client, admin_headers, admin_id, monkeypatch):
    monkeypatch.setattr("app.core.db_connections.test_connection", lambda details: ["work_orders"])
    _connect_database(client, admin_headers)
    seed_document(admin_id)

    monkeypatch.setattr(
        "app.api.v1.api.llm_provider.generate_json",
        _fake_generate_json('{"route": "document_chat", "reasoning": "seems doc-related"}'),
    )

    async def _fake_document_answer(state, current_user, history):
        return {"message": "Chat completed successfully", "answer": NO_ANSWER_IN_CONTEXT_TEXT, "blocked": False, "guardrail_events": [], "logs": []}

    from app.core.db_agent import DB_NO_ANSWER_TEXT

    def _fake_database_answer(question, connection, current_user, model, history, request_id, show_tier1_progress=True):
        return {"message": "Chat completed successfully", "answer": DB_NO_ANSWER_TEXT, "blocked": False, "guardrail_events": [], "logs": []}

    monkeypatch.setattr("app.api.v1.api.generate_document_answer", _fake_document_answer)
    monkeypatch.setattr("app.api.v1.api.generate_database_answer", _fake_database_answer)

    resp = client.post("/api/v1/chat", json={"question": "how many work orders are open"}, headers=admin_headers)
    assert resp.status_code == 200
    body = parse_sse_response(resp)
    assert body["answer"] == NO_ANSWER_IN_CONTEXT_TEXT
    assert body["routed_to"] == "document_chat"
    routing_event = next(e for e in body["graph_response"]["guardrail_events"] if e["stage"] == "orchestrator_routing")
    assert routing_event["source_fallback_used"] is False
