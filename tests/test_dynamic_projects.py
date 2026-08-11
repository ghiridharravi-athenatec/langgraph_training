NEW_PROJECT = {"id": "document-search", "name": "Document Search", "description": "Search across ingested documents"}


def test_registering_a_project_makes_it_appear_everywhere_automatically(client, admin_headers, user_headers, user_id):
    before = client.get("/api/v1/admin/projects", headers=admin_headers)
    assert NEW_PROJECT["id"] not in {p["id"] for p in before.json()}

    register = client.post("/api/v1/admin/projects", json=NEW_PROJECT, headers=admin_headers)
    assert register.status_code == 201
    assert register.json()["id"] == NEW_PROJECT["id"]

    after = client.get("/api/v1/admin/projects", headers=admin_headers)
    ids = {p["id"] for p in after.json()}
    assert NEW_PROJECT["id"] in ids
    assert "ragchatbot" in ids  # existing project still there, nothing hardcoded got clobbered

    # Not visible to the user yet - no grant.
    visible_before_grant = client.get("/api/v1/projects", headers=user_headers)
    assert NEW_PROJECT["id"] not in {p["id"] for p in visible_before_grant.json()}

    grant = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": [NEW_PROJECT["id"]]},
        headers=admin_headers,
    )
    assert grant.status_code == 200

    visible_after_grant = client.get("/api/v1/projects", headers=user_headers)
    assert [p["id"] for p in visible_after_grant.json()] == [NEW_PROJECT["id"]]


def test_registering_duplicate_project_id_rejected(client, admin_headers):
    resp = client.post("/api/v1/admin/projects", json={"id": "ragchatbot", "name": "Duplicate"}, headers=admin_headers)
    assert resp.status_code == 400


def test_invalid_project_id_rejected(client, admin_headers):
    resp = client.post("/api/v1/admin/projects", json={"id": "Not A Slug!", "name": "Bad"}, headers=admin_headers)
    assert resp.status_code == 422
