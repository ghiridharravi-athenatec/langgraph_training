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

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

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
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "16000"))
MIN_GROUNDEDNESS_SCORE = float(os.getenv("MIN_GROUNDEDNESS_SCORE", "0.3"))
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

# --- Chat history / semantic cache ---
SEMANTIC_CACHE_SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_SIMILARITY_THRESHOLD", "0.93"))
SEMANTIC_CACHE_MAX_CANDIDATES = int(os.getenv("SEMANTIC_CACHE_MAX_CANDIDATES", "200"))
