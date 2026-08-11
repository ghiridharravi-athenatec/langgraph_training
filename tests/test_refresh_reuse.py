from tests.conftest import signup


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_refresh_replay_of_same_token_is_rejected(client):
    signup(client, "replay@example.com", "ReplayPass123")
    login = client.post("/api/v1/auth/login", json={"email": "replay@example.com", "password": "ReplayPass123"})
    assert login.status_code == 200

    # Capture the refresh cookie issued at login, before any rotation happens.
    original_cookie = client.cookies.get("refresh_token")
    assert original_cookie

    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    old_access_token = login.json()["access_token"]

    # Replay the ORIGINAL login-issued refresh token (already superseded by `first`'s rotation).
    client.cookies.set("refresh_token", original_cookie)
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert "reuse" in replay.json()["detail"].lower()

    # Reuse detection revokes ALL sessions - even the access token from before the replay
    # (and from the legitimate first rotation) should now be rejected.
    assert client.get("/api/v1/auth/me", headers=_auth_headers(old_access_token)).status_code == 401


def test_normal_refresh_rotation_does_not_trigger_reuse_detection(client):
    signup(client, "normal@example.com", "NormalPass123")
    login = client.post("/api/v1/auth/login", json={"email": "normal@example.com", "password": "NormalPass123"})
    assert login.status_code == 200

    for _ in range(3):
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200

    me = client.get("/api/v1/auth/me", headers=_auth_headers(resp.json()["access_token"]))
    assert me.status_code == 200
