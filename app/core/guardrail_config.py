'''Admin-editable overrides for the guardrail pipeline's tunable thresholds and
lists ("rubrics") - question length, blocked keywords, PII entity types and
score threshold, daily quota, model-safety categories/threshold, intent
confidence, semantic cache thresholds, retrieval relevance, context budget,
groundedness, URL allowlist, and answer length. Structural checks (the
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
    "pii_entities": [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER",
        "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS", "CRYPTO",
        "PERSON", "LOCATION", "NRP", "MEDICAL_LICENSE",
    ],
    "pii_score_threshold": 0.4,
    "daily_token_quota": config.DAILY_TOKEN_QUOTA,
    "model_safety_categories": [
        "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
    ],
    "model_safety_threshold": "BLOCK_MEDIUM_AND_ABOVE",
    "intent_confidence_threshold": 0.8,
    "semantic_cache_similarity_threshold": config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD,
    "semantic_cache_max_candidates": config.SEMANTIC_CACHE_MAX_CANDIDATES,
    "min_relevance_score": 0.5,
    "max_context_chunks": 8,
    "max_context_chars": config.MAX_CONTEXT_CHARS,
    "min_groundedness_score": config.MIN_GROUNDEDNESS_SCORE,
    "allowed_url_domains": list(config.ALLOWED_URL_DOMAINS),
    "max_answer_length": 6000,
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
