import os

# Must be set before app.core.config (and anything importing it) is first imported.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-do-not-use-in-prod")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPass123")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

import mongomock
import pytest
from fastapi.testclient import TestClient

import app.utils.mongo as mongo_module

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


@pytest.fixture
def client(monkeypatch):
    '''Fresh in-memory Mongo + fresh app lifespan (admin/ragchatbot seeding) per test.'''
    fake_mongo_client = mongomock.MongoClient(tz_aware=True)
    monkeypatch.setattr(mongo_module, "get_mongo_client", lambda: fake_mongo_client)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client):
    resp = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token):
    return _auth_headers(admin_token)


def signup(client, email: str, password: str = "UserPass123"):
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def user_signup(client):
    return signup(client, "alice@example.com")


@pytest.fixture
def user_headers(user_signup):
    return _auth_headers(user_signup["access_token"])


@pytest.fixture
def user_id(user_signup):
    return user_signup["user"]["id"]
