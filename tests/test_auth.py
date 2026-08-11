from tests.conftest import signup


def test_signup_creates_user_with_no_permissions(client):
    data = signup(client, "bob@example.com")
    assert data["user"]["role"] == "user"
    assert data["user"]["projects"] == []
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


def test_signup_duplicate_email_rejected(client):
    signup(client, "dup@example.com")
    resp = client.post("/api/v1/auth/signup", json={"email": "dup@example.com", "password": "UserPass123"})
    assert resp.status_code == 400


def test_signup_weak_password_rejected(client):
    resp = client.post("/api/v1/auth/signup", json={"email": "weak@example.com", "password": "short"})
    assert resp.status_code == 422


def test_login_success(client):
    signup(client, "carol@example.com", "CarolPass123")
    resp = client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "CarolPass123"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password_rejected(client):
    signup(client, "dave@example.com", "DavePass123")
    resp = client.post("/api/v1/auth/login", json={"email": "dave@example.com", "password": "WrongPass123"})
    assert resp.status_code == 401


def test_login_unknown_email_rejected(client):
    resp = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WhoPass123"})
    assert resp.status_code == 401


def test_refresh_rotates_tokens(client):
    signup(client, "erin@example.com", "ErinPass123")
    login_resp = client.post("/api/v1/auth/login", json={"email": "erin@example.com", "password": "ErinPass123"})
    old_access_token = login_resp.json()["access_token"]

    refresh_resp = client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 200
    new_access_token = refresh_resp.json()["access_token"]
    assert new_access_token != old_access_token


def test_refresh_without_cookie_rejected(client):
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client, user_headers):
    resp = client.get("/api/v1/auth/me", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "user"
    assert body["projects"] == []
    assert "password_hash" not in body
