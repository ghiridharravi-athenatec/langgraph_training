from app.core import guardrail_config
from app.core.guardrails import (
    _redact_urls,
    evaluate_bias_detection,
    evaluate_context_injection,
    evaluate_topic_restriction,
    extract_token_count,
    validate_context_budget,
    validate_groundedness,
    validate_json_schema,
    validate_output,
    validate_quota,
)
from app.core.guardrails_agent import guardrails_agent


def test_context_budget_keeps_small_context_untouched():
    chunks = [{"content": "short chunk"}]
    event = validate_context_budget(chunks)
    assert event["passed"] is True
    assert event["dropped_chunks"] == 0
    assert event["reason"] is None
    assert len(event["kept_chunks"]) == 1


def test_context_budget_drops_chunks_over_budget():
    big_chunk = {"content": "x" * 20000}  # exceeds default MAX_CONTEXT_CHARS
    small_chunk = {"content": "y" * 100}
    event = validate_context_budget([big_chunk, small_chunk])
    assert event["passed"] is True  # non-blocking, just truncates
    assert event["dropped_chunks"] == 1
    assert len(event["kept_chunks"]) == 1
    assert event["reason"] is not None


def test_json_schema_validation_rejects_malformed_json():
    event = validate_json_schema("not json at all", {"answer": str}, stage="test_stage")
    assert event["passed"] is False
    assert event["parsed"] is None


def test_json_schema_validation_rejects_missing_field():
    event = validate_json_schema('{"other": "value"}', {"answer": str}, stage="test_stage")
    assert event["passed"] is False
    assert "answer" in event["reason"]


def test_json_schema_validation_rejects_wrong_type():
    event = validate_json_schema('{"answer": 123}', {"answer": str}, stage="test_stage")
    assert event["passed"] is False


def test_json_schema_validation_passes_valid_payload():
    event = validate_json_schema('{"answer": "hello", "confidence": 0.9}', {"answer": str}, stage="test_stage")
    assert event["passed"] is True
    assert event["parsed"]["answer"] == "hello"


def test_groundedness_skips_when_no_context():
    class FakeEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0]

    event = validate_groundedness("some answer", "", FakeEmbedder())
    assert event["passed"] is True
    assert event["score"] is None


def test_groundedness_blocks_dissimilar_answer():
    class FakeEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0] if "cat" in text else [0.0, 1.0]

    event = validate_groundedness("this is about a cat", "this document is entirely about dogs", FakeEmbedder())
    assert event["passed"] is False
    assert event["score"] is not None


def test_groundedness_passes_similar_answer():
    class FakeEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0]

    event = validate_groundedness("answer text", "context text", FakeEmbedder())
    assert event["passed"] is True


def test_quota_blocks_over_cap():
    event = validate_quota(tokens_used_today=999_999_999, daily_quota=1000)
    assert event["passed"] is False


def test_quota_passes_under_cap():
    event = validate_quota(tokens_used_today=0, daily_quota=1000)
    assert event["passed"] is True


def test_extract_token_count_reads_usage_metadata():
    class FakeUsage:
        total_token_count = 42
        prompt_token_count = 10
        candidates_token_count = 20

    class FakeResponse:
        usage_metadata = FakeUsage()

    assert extract_token_count(FakeResponse()) == 42


def test_extract_token_count_falls_back_to_sum():
    class FakeUsage:
        total_token_count = None
        prompt_token_count = 10
        candidates_token_count = 20

    class FakeResponse:
        usage_metadata = FakeUsage()

    assert extract_token_count(FakeResponse()) == 30


def test_extract_token_count_defaults_to_zero_without_usage_metadata():
    class FakeResponse:
        usage_metadata = None

    assert extract_token_count(FakeResponse()) == 0


def test_redact_urls_strips_non_allowlisted_links():
    redacted, stripped = _redact_urls("See https://evil.example.com/phish for details")
    assert "evil.example.com" in stripped
    assert "[LINK REMOVED]" in redacted
    assert "evil.example.com" not in redacted


def test_output_validation_reports_url_allowlist_check():
    result = validate_output("Visit https://random-domain.test/page for more info.")
    url_check = next(c for c in result["checks"] if c["check"] == "url_allowlist")
    assert url_check["passed"] is True  # non-blocking
    assert "random-domain.test" in url_check["reason"]
    assert "[LINK REMOVED]" in result["sanitized_answer"]


def test_evaluate_topic_restriction_blocks_out_of_scope():
    event = evaluate_topic_restriction(False, "unrelated to approved topics")
    assert event["passed"] is False
    assert event["reason"] == "unrelated to approved topics"


def test_evaluate_topic_restriction_uses_default_reason_when_missing():
    event = evaluate_topic_restriction(False, None)
    assert event["passed"] is False
    assert event["reason"]


def test_evaluate_topic_restriction_passes_in_scope():
    event = evaluate_topic_restriction(True, None)
    assert event["passed"] is True
    assert event["reason"] is None


def test_evaluate_bias_detection_blocks_flagged_answer():
    event = evaluate_bias_detection(True, "stereotyped by nationality")
    assert event["passed"] is False
    assert event["reason"] == "stereotyped by nationality"


def test_evaluate_bias_detection_passes_unflagged_answer():
    event = evaluate_bias_detection(False, None)
    assert event["passed"] is True


def test_evaluate_context_injection_flags_without_blocking():
    '''This check never blocks the turn - see its docstring - so "passed": False here
    means "genuinely found something" (real signal for the trace), not "block this
    answer" the way every other guardrail's False does.'''
    event = evaluate_context_injection(
        True, "high", "instructs the assistant to reveal its system prompt",
        "[Source: resume.pdf | Chunk 2 of 5]", "One of the documents contained something odd, so I left it out.",
    )
    assert event["passed"] is False
    assert event["stage"] == "context_injection_check"
    assert event["reason"] == "instructs the assistant to reveal its system prompt"
    assert event["injected_source"] == "[Source: resume.pdf | Chunk 2 of 5]"
    assert event["risk_level"] == "high"
    assert event["action"] == "excluded"
    assert event["user_notice"] == "One of the documents contained something odd, so I left it out."


def test_evaluate_context_injection_passes_clean_context():
    event = evaluate_context_injection(False, None, None, None, None)
    assert event["passed"] is True
    assert event["injected_source"] is None
    assert event["risk_level"] == "none"
    assert event["action"] == "none"
    assert event["user_notice"] is None


def test_evaluate_context_injection_defaults_risk_level_when_flagged_but_ungraded():
    event = evaluate_context_injection(True, None, "suspicious instruction found", "[Source: a.pdf | Chunk 1 of 1]", None)
    assert event["risk_level"] == "high"


def test_evaluate_context_injection_falls_back_to_default_notice_when_model_omits_one():
    event = evaluate_context_injection(True, "low", "reason", "[Source: a.pdf | Chunk 1 of 1]", None)
    assert event["user_notice"]  # non-empty fallback, not None/blank


def test_context_injection_fragments_empty_when_disabled():
    guardrail_config._cache["indirect_injection_detection_enabled"] = False
    assert guardrails_agent.context_injection_fragments() == ("", "")
    guardrail_config._cache["indirect_injection_detection_enabled"] = True


def test_context_injection_fragments_present_when_enabled():
    instructions, schema_fields = guardrails_agent.context_injection_fragments()
    assert "indirect prompt" in instructions.lower()
    assert "context_injection_flag" in schema_fields


def test_interpret_context_injection_none_when_disabled():
    guardrail_config._cache["indirect_injection_detection_enabled"] = False
    assert guardrails_agent.interpret_context_injection({"context_injection_flag": True}) is None
    guardrail_config._cache["indirect_injection_detection_enabled"] = True


def test_interpret_context_injection_none_when_field_absent():
    '''A response from a call that never spliced in the fragments (or a provider that
    dropped the field) shouldn't be misread as "checked and passed".'''
    assert guardrails_agent.interpret_context_injection({"answer": "no injection field here"}) is None


def test_interpret_context_injection_reads_all_fields():
    event = guardrails_agent.interpret_context_injection({
        "context_injection_flag": True,
        "context_injection_risk_level": "medium",
        "context_injection_reason": "odd imperative sentence",
        "context_injection_source": "[Source: notes.txt | Chunk 3 of 3]",
        "context_injection_notice": "One of the documents had something odd, so I set it aside.",
    })
    assert event["passed"] is False
    assert event["risk_level"] == "medium"
    assert event["injected_source"] == "[Source: notes.txt | Chunk 3 of 3]"
    assert event["user_notice"] == "One of the documents had something odd, so I set it aside."


def test_output_validation_blocks_compliance_keyword():
    # Mutates the in-process cache directly (not update_config, which persists to
    # Mongo) - the autouse _reset_guardrail_config_cache fixture in conftest.py
    # resets this back to DEFAULTS after the test, same as other direct-cache tests.
    original = guardrail_config.get_config()
    guardrail_config._cache = {**original, "compliance_keywords": original["compliance_keywords"] + ["guaranteed returns"]}
    result = validate_output("This fund offers guaranteed returns on your investment.")
    assert result["passed"] is False
    compliance_check = next(c for c in result["checks"] if c["check"] == "compliance_validation")
    assert compliance_check["passed"] is False


def test_output_validation_passes_without_compliance_keyword():
    result = validate_output("This is a plain, unremarkable answer.")
    compliance_check = next(c for c in result["checks"] if c["check"] == "compliance_validation")
    assert compliance_check["passed"] is True


def test_output_validation_flags_tone_without_blocking():
    result = validate_output("OMG this is amazing!! You gonna love it!!")
    tone_check = next(c for c in result["checks"] if c["check"] == "tone_check")
    assert tone_check["passed"] is True  # non-blocking
    assert tone_check["reason"] is not None
    assert result["passed"] is True


def test_output_validation_skips_tone_check_when_disabled():
    guardrail_config._cache = {**guardrail_config.get_config(), "tone_calibration_enabled": False}
    result = validate_output("OMG this is amazing!! You gonna love it!!")
    assert not any(c["check"] == "tone_check" for c in result["checks"])
