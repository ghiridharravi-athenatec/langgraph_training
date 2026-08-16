from app.core.security import create_password_reset_token
from tests.conftest import signup


def test_forgot_password_unknown_email_returns_generic_message(client):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert "reset link has been sent" in resp.json()["message"]


def test_forgot_password_known_email_returns_same_generic_message(client):
    signup(client, "reset-me@example.com")
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "reset-me@example.com"})
    assert resp.status_code == 200
    assert "reset link has been sent" in resp.json()["message"]


def test_reset_password_with_valid_token_changes_password(client):
    data = signup(client, "resetflow@example.com", "OldPass123")
    token = create_password_reset_token(data["user"]["id"])

    resp = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewPass456"})
    assert resp.status_code == 200

    old_login = client.post(
        "/api/v1/auth/login", json={"email": "resetflow@example.com", "password": "OldPass123"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login", json={"email": "resetflow@example.com", "password": "NewPass456"}
    )
    assert new_login.status_code == 200


def test_reset_password_token_cannot_be_reused(client):
    data = signup(client, "onetime@example.com", "OldPass123")
    token = create_password_reset_token(data["user"]["id"])

    first = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewPass456"})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "AnotherPass789"})
    assert second.status_code == 401


def test_reset_password_revokes_existing_sessions(client):
    data = signup(client, "revoke@example.com", "OldPass123")
    old_access_token = data["access_token"]
    token = create_password_reset_token(data["user"]["id"])

    client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewPass456"})

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_token}"})
    assert resp.status_code == 401


def test_change_password_requires_correct_current_password(client, user_headers):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WrongPass123", "new_password": "NewPass456"},
        headers=user_headers,
    )
    assert resp.status_code == 401


def test_change_password_success_reissues_working_session(client, user_headers):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "UserPass123", "new_password": "NewPass456"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me.status_code == 200

    old_me = client.get("/api/v1/auth/me", headers=user_headers)
    assert old_me.status_code == 401

    login = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "NewPass456"})
    assert login.status_code == 200
