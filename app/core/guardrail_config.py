'''Admin-editable overrides for the guardrail pipeline's tunable thresholds and
lists ("rubrics") - question length, blocked keywords, separate PII entity
types/score thresholds for chat input vs. chat output (ingestion has its own
defaults here too, but that one's exposed on the Document Ingestion upload
screen for any user, not the admin-only Guardrails page - see the
`ingest_pii_entities` comment below), daily quota, model-safety
categories/threshold, intent
confidence, semantic cache thresholds, retrieval relevance, context budget,
groundedness, URL allowlist, answer length, the approved-topics list (topic
restriction), the regulated-claim phrase list (compliance validation), and
the bias-detection/tone-calibration enable toggles. Structural checks (the
injection regex, the LLM injection-judgment prompt, JSON schema validation,
collection authorization) are deliberately NOT here - see
app/api/v1/guardrail_settings.py for why those stay fixed in code.

Deliberately NOT a live-Mongo-read-per-call: reading Mongo from inside a
guardrail check would mean every single chat/ingest request pays a round
trip (or, worse, a 30s pymongo server-selection timeout if Mongo is briefly
unreachable), and it would make every guardrail function require a mocked
Mongo client just to be unit-tested directly - which several existing tests
(tests/test_guardrails_extra.py, tests/test_semantic_cache.py) do without
going through the FastAPI app at all.

Instead: `_cache` is a plain in-process dict, seeded from DEFAULTS at import
time. It's only ever refreshed from Mongo explicitly - once at app startup
(bootstrap.seed_defaults -> refresh_from_mongo) - and updated in-process,
synchronously, whenever an admin saves a change via update_config()/
reset_to_defaults(). A guardrail function called directly with no app
startup (a bare unit test) simply sees DEFAULTS, unchanged from today.

Caveat: like rate_limit.py's in-memory limiter, this cache is per-process.
A multi-worker deployment needs a restart (or a future pub/sub refresh) for
every worker to observe an admin's edit, not just the one that served it.
'''

from typing import Any, Dict

from app.core import config
from app.core.logger import get_logger
from app.utils.mongo import get_guardrail_config_doc, reset_guardrail_config_doc, set_guardrail_config_doc

logger = get_logger(__name__)

# Six of these (daily_token_quota, semantic_cache_*, max_context_chars,
# min_groundedness_score, allowed_url_domains) were already env-var-driven via
# app/core/config.py - their factory default is read from there rather than
# duplicated as a literal, so an operator's env var still sets day-one
# behavior. Everything else here was a bare Python constant before; its
# factory default is just that same value, now living in one place.
DEFAULTS: Dict[str, Any] = {
    "min_question_length": 2,
    "max_question_length": 2000,
    "blocked_keywords": ["make a bomb", "kill yourself", "suicide method"],
    "input_pii_entities": [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
        "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS", "CRYPTO",
        "PERSON", "LOCATION", "NRP", "MEDICAL_LICENSE",
    ],
    "input_pii_score_threshold": 0.4,
    "output_pii_entities": [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
        "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS", "CRYPTO",
        "PERSON", "LOCATION", "NRP", "MEDICAL_LICENSE",
    ],
    "output_pii_score_threshold": 0.4,
    # Not admin-editable via the Guardrails page's config PUT - this is only the
    # fallback used when a document is ingested without an explicit entity
    # selection. The per-upload choice itself lives on the Document Ingestion
    # screen (see /ingest/pii-options and the `pii_entities` form field on
    # POST /ingest), open to every user, not just admins - a user redacting
    # their own upload doesn't need admin permission to pick what gets masked.
    "ingest_pii_entities": [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
        "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS", "CRYPTO",
        "PERSON", "LOCATION", "NRP", "MEDICAL_LICENSE",
    ],
    "ingest_pii_score_threshold": 0.4,
    "daily_token_quota": config.DAILY_TOKEN_QUOTA,
    "model_safety_categories": [
        "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
    ],
    "model_safety_threshold": "BLOCK_MEDIUM_AND_ABOVE",
    "intent_confidence_threshold": 0.8,
    "semantic_cache_similarity_threshold": config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD,
    "semantic_cache_max_candidates": config.SEMANTIC_CACHE_MAX_CANDIDATES,
    # 0.35 - BGE-M3 cosine similarity between a short question and a relevant
    # chunk routinely lands in the 0.3-0.6 range even for a genuinely good
    # match; 0.5 was quietly discarding legitimately relevant chunks before
    # they ever reached the context.
    "min_relevance_score": 0.35,
    "max_context_chunks": 8,
    # Not a guardrail (nothing here blocks a turn or protects against misuse) - a
    # retrieval-quality knob that happens to fit this module's existing live-tunable,
    # Mongo-backed override plumbing better than standing up a second admin-config
    # system for two fields. See retrieve.py's route_documents_node. Routing always
    # falls back to an unfiltered (today's) search below this confidence floor or
    # when disabled - it can only narrow retrieval, never block it. The score itself
    # is query-token coverage (fraction of the question's distinct words found in a
    # given document), not a BM25 relevance score - BM25's IDF weighting degenerates
    # at the small per-user document counts this app actually has (see
    # route_documents_node's comment for why).
    "document_routing_enabled": True,
    "document_routing_min_score": 0.15,
    "max_context_chars": config.MAX_CONTEXT_CHARS,
    "min_groundedness_score": config.MIN_GROUNDEDNESS_SCORE,
    "allowed_url_domains": list(config.ALLOWED_URL_DOMAINS),
    "max_answer_length": 6000,
    # Empty = no restriction (default, so existing projects are unaffected). When
    # set, the intent-classification call also judges whether the question's
    # subject matter falls within this list - see guardrails.build_topic_restriction_instructions.
    "allowed_topics": [],
    # Definitive regulated-claim phrases (financial/medical/legal) that block the
    # generated answer, same mechanism as blocked_keywords but a separate list
    # since these are about liability/compliance, not safety.
    "compliance_keywords": ["guaranteed returns", "guaranteed profit", "risk-free investment", "guaranteed to cure"],
    "bias_detection_enabled": True,
    "tone_calibration_enabled": True,
    # Model self-reports whether the retrieved Context (not the answer) contains
    # indirect prompt injection - riding on the same answer-generation call as bias
    # detection above. See guardrails.py's INDIRECT_INJECTION_DETECTION_* section.
    "indirect_injection_detection_enabled": True,
}

_cache: Dict[str, Any] = dict(DEFAULTS)


def get_config() -> Dict[str, Any]:
    '''Read access for every guardrail check. Always in-process - never touches Mongo.'''
    return _cache


def refresh_from_mongo() -> Dict[str, Any]:
    '''Loads persisted overrides on top of DEFAULTS. Called once at app startup;
    never from inside a guardrail check.'''
    global _cache
    stored = get_guardrail_config_doc()
    _cache = {**DEFAULTS, **stored}
    if stored:
        logger.info("Loaded guardrail config overrides from Mongo: %s", sorted(stored.keys()))
    return _cache


def update_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    '''Persists a partial update to Mongo and applies it to the in-process cache
    immediately, so it's live for this process's very next guardrail check.'''
    global _cache
    if not patch:
        return _cache
    stored = set_guardrail_config_doc(patch)
    _cache = {**DEFAULTS, **stored}
    logger.info("Guardrail config updated: %s", sorted(patch.keys()))
    return _cache


def reset_to_defaults() -> Dict[str, Any]:
    global _cache
    stored = reset_guardrail_config_doc(DEFAULTS)
    _cache = {**DEFAULTS, **stored}
    logger.info("Guardrail config reset to defaults")
    return _cache
