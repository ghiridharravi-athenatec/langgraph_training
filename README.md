---
title: RAG Chatbot API
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# RAG Chatbot — backend

FastAPI + LangGraph RAG pipeline (MongoDB Atlas Vector Search, Gemini, local
Presidio/spaCy PII detection) deployed here as a Hugging Face Space. The React
frontend is deployed separately (Vercel/Cloudflare Pages) and talks to this
Space's `/api/v1` routes.

## Required Space secrets

Set these under Settings → Repository secrets:

| Secret | Notes |
| --- | --- |
| `MONGO_URI` | MongoDB Atlas connection string (Vector Search-enabled cluster) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `JWT_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PII_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — without this, masked PII becomes unrecoverable every time the Space restarts/sleeps |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Initial admin account, created on first boot |
| `FRONTEND_ORIGIN` | The deployed frontend's origin, e.g. `https://your-app.vercel.app` |
| `COOKIE_SECURE` | `true` — the frontend and this Space are different origins, so the refresh cookie needs `Secure` + `SameSite=None` to survive the cross-site request |
| `COOKIE_SAMESITE` | `none` |

Everything else in `.env.example` has a working default.

## Notes

- Free CPU Spaces sleep after inactivity; the next request pays the cost of
  reloading the embedding/NER/OCR models (well over the usual cold-start
  delay of a plain web app).
- The container filesystem is ephemeral on the free tier - uploaded file
  copies and OCR-extracted images don't survive a restart, but that's fine
  here since the actual chunk text is already persisted in MongoDB.
