from app.utils.mongo import add_message, create_conversation
from tests.conftest import signup


def _grant(client, admin_headers, user_id, project_ids):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": project_ids},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def _seed_conversation(user_id, question="hello", answer="hi there", project_id="ragchatbot", **extra):
    conversation = create_conversation(user_id, project_id)
    add_message(conversation["_id"], user_id, "user", question)
    add_message(conversation["_id"], user_id, "assistant", answer, blocked=False, cached=False, **extra)
    return conversation


def test_user_without_traces_access_is_forbidden(client, user_headers):
    resp = client.get("/api/v1/traces/users", headers=user_headers)
    assert resp.status_code == 403


def test_traces_user_sees_only_themselves_in_user_list(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])

    resp = client.get("/api/v1/traces/users", headers=user_headers)
    assert resp.status_code == 200
    assert [u["id"] for u in resp.json()] == [user_id]


def test_admin_sees_every_user_in_user_list(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])

    resp = client.get("/api/v1/traces/users", headers=admin_headers)
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()}
    admin_id = client.get("/api/v1/auth/me", headers=admin_headers).json()["id"]
    assert {user_id, admin_id} <= ids


def test_traces_user_can_view_their_own_conversations(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    _seed_conversation(user_id)

    resp = client.get(f"/api/v1/traces/users/{user_id}/conversations", headers=user_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_traces_user_cannot_view_another_users_conversations(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    other = signup(client, "other-conversations@example.com")
    _seed_conversation(other["user"]["id"])

    resp = client.get(f"/api/v1/traces/users/{other['user']['id']}/conversations", headers=user_headers)
    assert resp.status_code == 403


def test_traces_user_cannot_view_another_users_turns(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    other = signup(client, "other-turns@example.com")
    _seed_conversation(other["user"]["id"])

    resp = client.get(f"/api/v1/traces/users/{other['user']['id']}/turns", headers=user_headers)
    assert resp.status_code == 403


def test_traces_user_cannot_view_another_users_conversation_messages(client, admin_headers, user_headers, user_id):
    '''The narrowest and most important case: even knowing (or guessing) another user's
    conversation_id directly must not be enough to read their messages.'''
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    other = signup(client, "other-messages@example.com")
    conversation = _seed_conversation(other["user"]["id"])

    resp = client.get(f"/api/v1/traces/conversations/{conversation['_id']}/messages", headers=user_headers)
    assert resp.status_code == 403


def test_admin_can_view_any_users_conversations_turns_and_messages(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    conversation = _seed_conversation(user_id)

    assert client.get(f"/api/v1/traces/users/{user_id}/conversations", headers=admin_headers).status_code == 200
    assert client.get(f"/api/v1/traces/users/{user_id}/turns", headers=admin_headers).status_code == 200
    assert (
        client.get(f"/api/v1/traces/conversations/{conversation['_id']}/messages", headers=admin_headers).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# guardrail_events round-trip (database-chatbot turns) + project_id scoping
# ---------------------------------------------------------------------------

_TOOL_CALL_EVENTS = [{"stage": "db_agent_tool_call", "tool": "run_query", "passed": True, "reason": None}]


def test_guardrail_events_round_trip_for_a_database_turn(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    conversation = _seed_conversation(
        user_id, question="how many users", answer="42 users.",
        project_id="database-chatbot", guardrail_events=_TOOL_CALL_EVENTS,
    )

    turns = client.get(f"/api/v1/traces/users/{user_id}/turns", headers=admin_headers).json()
    turn = next(t for t in turns if t["conversation_id"] == conversation["_id"])
    assert turn["guardrail_events"] == _TOOL_CALL_EVENTS
    assert turn["graph_response"] is None

    messages = client.get(
        f"/api/v1/traces/conversations/{conversation['_id']}/messages", headers=admin_headers
    ).json()
    assert messages[1]["guardrail_events"] == _TOOL_CALL_EVENTS


def test_project_id_filters_traced_user_conversation_count(client, admin_headers, admin_id):
    _seed_conversation(admin_id, project_id="ragchatbot")
    _seed_conversation(admin_id, project_id="database-chatbot")
    _seed_conversation(admin_id, project_id="database-chatbot")

    doc_users = client.get("/api/v1/traces/users", params={"project_id": "ragchatbot"}, headers=admin_headers).json()
    db_users = client.get("/api/v1/traces/users", params={"project_id": "database-chatbot"}, headers=admin_headers).json()
    all_users = client.get("/api/v1/traces/users", headers=admin_headers).json()

    admin_row = lambda rows: next(u for u in rows if u["id"] == admin_id)
    assert admin_row(doc_users)["conversation_count"] == 1
    assert admin_row(db_users)["conversation_count"] == 2
    assert admin_row(all_users)["conversation_count"] == 3


def test_get_trace_turn_by_id_returns_matching_turn(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    conversation = _seed_conversation(user_id, question="what is x", answer="x is y")

    turns = client.get(f"/api/v1/traces/users/{user_id}/turns", headers=user_headers).json()
    turn_id = turns[0]["id"]

    resp = client.get(f"/api/v1/traces/turns/{turn_id}", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == turn_id
    assert body["question"] == "what is x"
    assert body["answer"] == "x is y"
    assert body["conversation_id"] == conversation["_id"]


def test_get_trace_turn_by_id_forbidden_for_another_user(client, admin_headers, user_headers, user_id):
    _grant(client, admin_headers, user_id, ["guardrail-traces"])
    other = signup(client, "other-turn-detail@example.com")
    _seed_conversation(other["user"]["id"])

    other_turns = client.get(f"/api/v1/traces/users/{other['user']['id']}/turns", headers=admin_headers).json()
    turn_id = other_turns[0]["id"]

    resp = client.get(f"/api/v1/traces/turns/{turn_id}", headers=user_headers)
    assert resp.status_code == 403


def test_get_trace_turn_by_id_404_for_unknown_id(client, admin_headers):
    resp = client.get("/api/v1/traces/turns/does-not-exist", headers=admin_headers)
    assert resp.status_code == 404


def test_project_id_filters_traced_turns(client, admin_headers, admin_id):
    _seed_conversation(admin_id, question="a document question", project_id="ragchatbot")
    _seed_conversation(admin_id, question="a database question", project_id="database-chatbot")

    db_turns = client.get(
        f"/api/v1/traces/users/{admin_id}/turns", params={"project_id": "database-chatbot"}, headers=admin_headers
    ).json()
    assert [t["question"] for t in db_turns] == ["a database question"]

    doc_turns = client.get(
        f"/api/v1/traces/users/{admin_id}/turns", params={"project_id": "ragchatbot"}, headers=admin_headers
    ).json()
    assert [t["question"] for t in doc_turns] == ["a document question"]

    all_turns = client.get(f"/api/v1/traces/users/{admin_id}/turns", headers=admin_headers).json()
    assert {t["question"] for t in all_turns} == {"a document question", "a database question"}
