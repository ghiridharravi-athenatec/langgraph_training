from app.utils.mongo import add_message, create_conversation
from tests.conftest import signup


def _grant(client, admin_headers, user_id, project_ids):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": project_ids},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def _seed_conversation(user_id, question="hello", answer="hi there"):
    conversation = create_conversation(user_id)
    add_message(conversation["_id"], user_id, "user", question)
    add_message(conversation["_id"], user_id, "assistant", answer, blocked=False, cached=False)
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
