from app.core import config
from tests.conftest import signup


def test_lockout_after_threshold_failed_attempts(client):
    signup(client, "lockout@example.com", "RealPass123")

    for i in range(config.LOGIN_LOCKOUT_THRESHOLD):
        resp = client.post(
            "/api/v1/auth/login", json={"email": "lockout@example.com", "password": "WrongPass123"}
        )
        assert resp.status_code == 401, f"attempt {i} should be a plain auth failure, got {resp.status_code}"

    locked = client.post(
        "/api/v1/auth/login", json={"email": "lockout@example.com", "password": "WrongPass123"}
    )
    assert locked.status_code == 429

    # Even the CORRECT password is rejected while locked out.
    still_locked = client.post(
        "/api/v1/auth/login", json={"email": "lockout@example.com", "password": "RealPass123"}
    )
    assert still_locked.status_code == 429


def test_successful_login_resets_failure_count(client):
    signup(client, "resets@example.com", "RealPass123")

    for _ in range(config.LOGIN_LOCKOUT_THRESHOLD - 1):
        client.post("/api/v1/auth/login", json={"email": "resets@example.com", "password": "WrongPass123"})

    ok = client.post("/api/v1/auth/login", json={"email": "resets@example.com", "password": "RealPass123"})
    assert ok.status_code == 200

    # Back below threshold again after a successful login - one more wrong guess shouldn't lock it.
    wrong_again = client.post(
        "/api/v1/auth/login", json={"email": "resets@example.com", "password": "WrongPass123"}
    )
    assert wrong_again.status_code == 401


def test_lockout_is_per_email(client):
    signup(client, "victim@example.com", "RealPass123")
    signup(client, "bystander@example.com", "RealPass123")

    for _ in range(config.LOGIN_LOCKOUT_THRESHOLD + 1):
        client.post("/api/v1/auth/login", json={"email": "victim@example.com", "password": "WrongPass123"})

    unaffected = client.post(
        "/api/v1/auth/login", json={"email": "bystander@example.com", "password": "RealPass123"}
    )
    assert unaffected.status_code == 200
