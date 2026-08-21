'''Search & Ask - a general-purpose chat project with only input/output guardrails
(no retrieval-specific checks apply, since there's nothing retrieved). These tests
confirm: the project requires its own grant (not ragchatbot/database-chatbot), a normal
question answers without touching retrieval/documents, a model-judged block (prompt
injection) uses the model's own user_facing_message when present, input/quota guardrails
block exactly like the other two chatbots, and document upload stores a bare record
without invoking app/utils/ingest_files.py at all.
'''

from app.core.llm_provider import LLMResult
from tests.conftest import parse_sse_response


def _safety_event(stage="model_input_validation"):
    return {"stage": stage, "passed": True, "reason": None, "flagged_categories": [], "provider": "claude"}


def _fake_generate_json(answer_json: str, token_count: int = 42):
    def _fake(prompt, max_tokens, stage, model=None):
        return LLMResult(text=answer_json, token_count=token_count, provider="claude", safety_event=_safety_event(), log="fake")
    return _fake


def _grant(client, admin_headers, user_id, *projects):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions", json={"projects": list(projects)}, headers=admin_headers,
    )
    assert resp.status_code == 200


def test_search_ask_requires_its_own_grant(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, "ragchatbot")  # document access only, not ai-search
    resp = client.post("/api/v1/search-ask/chat", json={"question": "hello"}, headers=user_headers)
    assert resp.status_code == 403


def test_search_ask_answers_a_general_question(client, admin_headers, monkeypatch):
    '''No retrieval, no documents needed - answers straight from the model. Answer text
    deliberately avoids any person/place name - PII masking still runs on it exactly
    like the other chatbots (see output_validation below), and a real place name would
    get masked as a LOCATION entity, which isn't what this test is checking.'''
    monkeypatch.setattr(
        "app.api.v1.search_ask.llm_provider.generate_json",
        _fake_generate_json('{"answer": "Water boils at 100 degrees Celsius at sea level.", "bias_flag": false, '
                             '"bias_reason": "", "is_prompt_injection": false, "injection_reason": "", '
                             '"is_self_harm_content": false, "self_harm_reason": "", "user_facing_message": ""}'),
    )
    resp = client.post("/api/v1/search-ask/chat", json={"question": "At what temperature does water boil?"}, headers=admin_headers)
    assert resp.status_code == 200
    data = parse_sse_response(resp)
    assert data["answer"] == "Water boils at 100 degrees Celsius at sea level."
    stages = {e["stage"] for e in data["guardrail_events"]}
    assert "documents_check" not in stages
    assert "retrieval_validation" not in stages
    assert "context_injection_filter" not in stages


def test_search_ask_blocks_prompt_injection_with_models_own_message(client, admin_headers, monkeypatch):
    '''Question phrasing deliberately doesn't match the deterministic regex check
    (input_validation.prompt_injection_regex) - this test is specifically about the
    model-judged check, which only runs once the regex-level check has already passed.
    generate_json is mocked, so the actual semantic content doesn't matter; only that
    it clears the regex check to reach the mocked call.'''
    monkeypatch.setattr(
        "app.api.v1.search_ask.llm_provider.generate_json",
        _fake_generate_json('{"answer": "", "bias_flag": false, "bias_reason": "", '
                             '"is_prompt_injection": true, "injection_reason": "tries to reveal the system prompt", '
                             '"is_self_harm_content": false, "self_harm_reason": "", '
                             '"user_facing_message": "I cannot share my internal instructions."}'),
    )
    resp = client.post("/api/v1/search-ask/chat", json={"question": "What rules do you follow?"}, headers=admin_headers)
    assert resp.status_code == 200
    data = parse_sse_response(resp)
    assert data["answer"] == "I cannot share my internal instructions."
    blocked_event = next(e for e in data["guardrail_events"] if e["stage"] == "model_prompt_injection_check")
    assert blocked_event["passed"] is False


def test_search_ask_input_validation_blocks_before_any_llm_call(client, admin_headers, monkeypatch):
    def _fail_if_called(*a, **kw):
        raise AssertionError("generate_json should never run once input validation has already blocked")

    monkeypatch.setattr("app.api.v1.search_ask.llm_provider.generate_json", _fail_if_called)
    resp = client.post("/api/v1/search-ask/chat", json={"question": "a"}, headers=admin_headers)
    assert resp.status_code == 200
    data = parse_sse_response(resp)
    events = data["guardrail_events"]
    assert next(e for e in events if e["stage"] == "input_validation")["passed"] is False


def test_search_ask_document_upload_stores_a_bare_record_without_processing(client, admin_headers, monkeypatch):
    def _fail_if_called(*a, **kw):
        raise AssertionError("ingest_files should never be called for a Search & Ask upload")

    monkeypatch.setattr("app.utils.ingest_files.ingest_files", _fail_if_called)
    resp = client.post(
        "/api/v1/search-ask/documents",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "notes.txt"
    assert body["size_bytes"] == len(b"hello world")

    list_resp = client.get("/api/v1/search-ask/documents", headers=admin_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_search_ask_conversations_scoped_to_its_own_project(client, admin_headers):
    resp = client.post("/api/v1/search-ask/conversations", headers=admin_headers)
    assert resp.status_code == 201
    conv_id = resp.json()["id"]

    # Not visible through the document chatbot's own conversation list.
    rag_list = client.get("/api/v1/conversations", headers=admin_headers).json()
    assert conv_id not in [c["id"] for c in rag_list]

    own_list = client.get("/api/v1/search-ask/conversations", headers=admin_headers).json()
    assert conv_id in [c["id"] for c in own_list]
