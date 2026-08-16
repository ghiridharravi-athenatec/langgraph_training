import os

from dotenv import load_dotenv

# Must run before any os.getenv() call below. Previously relied on some other module
# happening to call load_dotenv() before first importing this one - fragile import-order
# luck that broke silently (ADMIN_EMAIL/ADMIN_PASSWORD/JWT_SECRET_KEY read as unset) once
# app.utils.mongo started importing this module earlier in the chain.
load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
# No trailing slash - CORSMiddleware does an exact match against the browser's
# Origin header, which never has one (https://host, not https://host/).
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://langgraph-training.vercel.app")

REFRESH_COOKIE_NAME = "refresh_token"

# Local/docker-compose dev serves the frontend and API from the same origin, so
# the default (Lax, non-Secure) cookie works fine over plain HTTP. A split
# deployment - frontend on Vercel, backend on a different origin (e.g. a
# Hugging Face Space) - is cross-site from the browser's point of view, which
# requires SameSite=None + Secure (browsers reject SameSite=None without
# Secure) for the refresh cookie to be sent back at all. Set both when
# deploying split.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")

# --- Ingestion guardrails ---
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))

# --- Retrieval / generation guardrails ---
# 8000 - with max_context_chunks capped at 8 and each ingested chunk targeting
# ~700 chars, 8 chunks tops out around ~5,600 chars in practice; the old
# 16,000 default was never actually the binding constraint, just dead
# headroom that looked like a real budget.
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "8000"))
# 0.35 - BGE-M3 cosine similarity between an answer and its supporting context
# commonly lands lower than intuition suggests even when well-grounded; 0.3
# was already lenient, nudged up slightly so this check isn't purely
# decorative while staying well clear of penalizing normal phrasing drift.
MIN_GROUNDEDNESS_SCORE = float(os.getenv("MIN_GROUNDEDNESS_SCORE", "0.35"))
ALLOWED_URL_DOMAINS = [d.strip().lower() for d in os.getenv("ALLOWED_URL_DOMAINS", "").split(",") if d.strip()]
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

# --- Operational guardrails ---
DAILY_TOKEN_QUOTA = int(os.getenv("DAILY_TOKEN_QUOTA", "50000"))
CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT", "20"))
INGEST_RATE_LIMIT = int(os.getenv("INGEST_RATE_LIMIT", "5"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# --- Auth guardrails ---
LOGIN_LOCKOUT_THRESHOLD = int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "5"))
LOGIN_LOCKOUT_WINDOW_MINUTES = int(os.getenv("LOGIN_LOCKOUT_WINDOW_MINUTES", "15"))

# --- Password reset ---
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30"))
PASSWORD_RESET_RATE_LIMIT = int(os.getenv("PASSWORD_RESET_RATE_LIMIT", "3"))
PASSWORD_RESET_RATE_WINDOW_MINUTES = int(os.getenv("PASSWORD_RESET_RATE_WINDOW_MINUTES", "60"))

# --- Email (SMTP) - only used to deliver password reset links. Unset by
# default; send_email() logs a warning and no-ops rather than raising, so a
# missing/misconfigured mail server degrades to "no email sent", not a 500.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "") or SMTP_USERNAME
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() == "true"

# --- Chat history / semantic cache ---
# 0.90 - 0.93 rarely fired in practice since even a near-identical rephrasing
# of the same question often lands in the low 0.90s on BGE-M3; still high
# enough that two genuinely different questions won't false-positive into
# sharing an answer.
SEMANTIC_CACHE_SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_SIMILARITY_THRESHOLD", "0.90"))
SEMANTIC_CACHE_MAX_CANDIDATES = int(os.getenv("SEMANTIC_CACHE_MAX_CANDIDATES", "200"))

# --- LLM provider (Claude primary, Gemini fallback) ---
# Every text-generation call in the pipeline (intent classification, answer
# generation, the database chat agent) goes through app/core/llm_provider.py,
# which tries Claude first and falls back to Gemini on any failure - see that
# module's docstring for why (and what's lost on the Claude path: the
# Gemini-only model-safety guardrail).
# Previously read ad hoc via os.getenv(...) at each Gemini call site
# (app/utils/llm.py, app/utils/retrieve.py, app/api/v1/api.py) instead of
# living here - centralized now that llm_provider.py needs it too.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
# UI-facing model choice (see the model picker next to the chat input) maps here
# rather than accepting a raw model id from the client - keeps the set of
# reachable models to ones this app actually intends to support.
CLAUDE_MODEL_CHOICES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}
# Was a string literal duplicated in both app/utils/llm.py and app/utils/retrieve.py;
# centralized here so the Gemini fallback path has one source of truth too.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# --- Database Ingestion ("chat with your database") ---
# Fernet key for encrypting saved external DB connection credentials at rest -
# deliberately separate from guardrails.py's PII_ENCRYPTION_KEY so the two can be
# rotated independently. Same ephemeral-key-with-warning fallback behavior as
# that key - see app/core/db_connections.py.
DB_CREDENTIAL_ENCRYPTION_KEY = os.getenv("DB_CREDENTIAL_ENCRYPTION_KEY", "")
DB_AGENT_MAX_TOOL_CALLS = int(os.getenv("DB_AGENT_MAX_TOOL_CALLS", "6"))
DB_QUERY_ROW_LIMIT = int(os.getenv("DB_QUERY_ROW_LIMIT", "200"))
DB_QUERY_TIMEOUT_SECONDS = int(os.getenv("DB_QUERY_TIMEOUT_SECONDS", "15"))

# --- Chat conversation history ("context window") ---
# How many prior (question, answer) turns from the same conversation get fed back
# into the prompt so follow-up questions have continuity. Counted in turns, not
# tokens/characters - kept deliberately small since every turn added here is
# extra prompt content on every subsequent request in the conversation.
CHAT_HISTORY_MAX_TURNS = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "6"))

# --- Encryption key strictness ---
# Off by default so local dev/tests never need either key configured - both
# PII_ENCRYPTION_KEY and DB_CREDENTIAL_ENCRYPTION_KEY silently fall back to an
# ephemeral, restart-losing key with a warning log otherwise. A production
# deployment that wants a missing/malformed key to fail startup loudly instead
# of quietly generating unrecoverable data can opt in with this.
REQUIRE_PERSISTENT_ENCRYPTION_KEYS = os.getenv("REQUIRE_PERSISTENT_ENCRYPTION_KEYS", "false").strip().lower() == "true"
