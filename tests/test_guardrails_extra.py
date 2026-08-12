from app.core.guardrails import (
    _redact_urls,
    extract_token_count,
    validate_context_budget,
    validate_groundedness,
    validate_json_schema,
    validate_output,
    validate_quota,
)


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


def test_quota_admin_always_passes():
    event = validate_quota(tokens_used_today=999_999_999, is_admin=True)
    assert event["passed"] is True


def test_quota_blocks_over_cap():
    event = validate_quota(tokens_used_today=999_999_999, is_admin=False)
    assert event["passed"] is False


def test_quota_passes_under_cap():
    event = validate_quota(tokens_used_today=0, is_admin=False)
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
