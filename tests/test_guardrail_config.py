from app.core import config, guardrail_config
from app.core.guardrails import validate_output


def _grant_traces(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["guardrail-traces"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def test_default_config_matches_documented_defaults(client, admin_headers):
    resp = client.get("/api/v1/traces/guardrail-config", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["daily_token_quota"] == config.DAILY_TOKEN_QUOTA
    assert body["intent_confidence_threshold"] == 0.8
    assert body["max_answer_length"] == 6000


def test_user_without_traces_access_is_forbidden(client, user_headers):
    resp = client.get("/api/v1/traces/guardrail-config", headers=user_headers)
    assert resp.status_code == 403


def test_traces_access_grants_read_but_not_write(client, admin_headers, user_headers, user_id):
    _grant_traces(client, admin_headers, user_id)

    read_resp = client.get("/api/v1/traces/guardrail-config", headers=user_headers)
    assert read_resp.status_code == 200

    write_resp = client.put("/api/v1/traces/guardrail-config", json={"max_answer_length": 500}, headers=user_headers)
    assert write_resp.status_code == 403


def test_admin_update_takes_effect_immediately(client, admin_headers):
    resp = client.put("/api/v1/traces/guardrail-config", json={"max_answer_length": 150}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["max_answer_length"] == 150

    get_resp = client.get("/api/v1/traces/guardrail-config", headers=admin_headers)
    assert get_resp.json()["max_answer_length"] == 150

    # The in-process cache guardrail functions read from is updated synchronously by
    # the PUT above - no restart needed to observe it.
    result = validate_output("x" * 300)
    assert result["passed"] is True
    assert len(result["sanitized_answer"]) == 153  # 150 chars + "..."


def test_reset_restores_defaults(client, admin_headers):
    client.put("/api/v1/traces/guardrail-config", json={"daily_token_quota": 1}, headers=admin_headers)
    assert guardrail_config.get_config()["daily_token_quota"] == 1

    resp = client.post("/api/v1/traces/guardrail-config/reset", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["daily_token_quota"] == config.DAILY_TOKEN_QUOTA
    assert guardrail_config.get_config()["daily_token_quota"] == config.DAILY_TOKEN_QUOTA


def test_update_rejects_out_of_range_score(client, admin_headers):
    resp = client.put("/api/v1/traces/guardrail-config", json={"pii_score_threshold": 5}, headers=admin_headers)
    assert resp.status_code == 422


def test_update_rejects_unknown_pii_entity(client, admin_headers):
    resp = client.put("/api/v1/traces/guardrail-config", json={"pii_entities": ["NOT_A_REAL_ENTITY"]}, headers=admin_headers)
    assert resp.status_code == 422


def test_update_rejects_min_greater_than_max_question_length(client, admin_headers):
    resp = client.put(
        "/api/v1/traces/guardrail-config",
        json={"min_question_length": 100, "max_question_length": 50},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_partial_update_leaves_other_fields_untouched(client, admin_headers):
    client.put("/api/v1/traces/guardrail-config", json={"max_answer_length": 777}, headers=admin_headers)
    resp = client.put("/api/v1/traces/guardrail-config", json={"daily_token_quota": 42}, headers=admin_headers)
    body = resp.json()
    assert body["daily_token_quota"] == 42
    assert body["max_answer_length"] == 777  # untouched by the second, unrelated PUT
