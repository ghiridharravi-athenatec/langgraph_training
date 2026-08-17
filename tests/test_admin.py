from tests.conftest import signup


def test_non_admin_forbidden_from_every_admin_route(client, user_headers, user_id):
    assert client.get("/api/v1/admin/users", headers=user_headers).status_code == 403
    assert client.get("/api/v1/admin/projects", headers=user_headers).status_code == 403
    assert client.post(
        "/api/v1/admin/projects",
        json={"id": "x", "name": "X"},
        headers=user_headers,
    ).status_code == 403
    assert client.get(f"/api/v1/admin/users/{user_id}/permissions", headers=user_headers).status_code == 403
    assert client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=user_headers,
    ).status_code == 403


def test_unauthenticated_forbidden_from_admin_routes(client):
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401


def test_admin_can_login(client, admin_headers):
    resp = client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_admin_sees_all_users(client, admin_headers, user_signup):
    resp = client.get("/api/v1/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "alice@example.com" in emails
    assert "admin@example.com" in emails
    for u in resp.json():
        assert "password_hash" not in u
        assert "password" not in u


def test_admin_sees_seeded_ragchatbot_project(client, admin_headers):
    resp = client.get("/api/v1/admin/projects", headers=admin_headers)
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert "ragchatbot" in ids


def test_admin_grant_and_revoke_permission(client, admin_headers, user_id):
    grant = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert grant.status_code == 200
    assert grant.json() == ["ragchatbot"]

    check = client.get(f"/api/v1/admin/users/{user_id}/permissions", headers=admin_headers)
    assert check.json() == ["ragchatbot"]

    revoke = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": []},
        headers=admin_headers,
    )
    assert revoke.status_code == 200
    assert revoke.json() == []


def test_grant_unknown_project_rejected(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["does-not-exist"]},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_grant_to_unknown_user_404s(client, admin_headers):
    resp = client.put(
        "/api/v1/admin/users/no-such-user/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_repeated_grant_is_idempotent_not_duplicated(client, admin_headers, user_id):
    for _ in range(3):
        resp = client.put(
            f"/api/v1/admin/users/{user_id}/permissions",
            json={"projects": ["ragchatbot"]},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    check = client.get(f"/api/v1/admin/users/{user_id}/permissions", headers=admin_headers)
    assert check.json() == ["ragchatbot"]


def test_admin_can_promote_user_to_admin(client, admin_headers, user_id, user_headers):
    resp = client.put(f"/api/v1/admin/users/{user_id}/role", json={"role": "admin"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    # Role isn't embedded in the JWT - the promoted user's existing access token
    # picks it up on its very next request, no re-login needed.
    me = client.get("/api/v1/auth/me", headers=user_headers)
    assert me.json()["role"] == "admin"


def test_admin_can_demote_another_admin(client, admin_headers, user_id):
    client.put(f"/api/v1/admin/users/{user_id}/role", json={"role": "admin"}, headers=admin_headers)
    resp = client.put(f"/api/v1/admin/users/{user_id}/role", json={"role": "user"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


def test_admin_cannot_change_their_own_role(client, admin_headers, admin_id):
    resp = client.put(f"/api/v1/admin/users/{admin_id}/role", json={"role": "user"}, headers=admin_headers)
    assert resp.status_code == 400


def test_update_role_for_unknown_user_404s(client, admin_headers):
    resp = client.put("/api/v1/admin/users/no-such-user/role", json={"role": "admin"}, headers=admin_headers)
    assert resp.status_code == 404


def test_update_role_rejects_invalid_value(client, admin_headers, user_id):
    resp = client.put(f"/api/v1/admin/users/{user_id}/role", json={"role": "superuser"}, headers=admin_headers)
    assert resp.status_code == 422


def test_non_admin_forbidden_from_role_route(client, user_headers, admin_id):
    resp = client.put(f"/api/v1/admin/users/{admin_id}/role", json={"role": "user"}, headers=user_headers)
    assert resp.status_code == 403
