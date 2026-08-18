'''In-process "what's happening right now" tracker for the chat screen's thinking
indicator - a request_id the client generates up front (see api.py's /chat and
database.py's /database/chat) maps to whatever friendly stage label the pipeline
last reported, polled by GET /progress/{request_id}.

Same per-process, not-multi-worker-safe caveat as rate_limit.py's limiter and
guardrail_config.py's cache (see their docstrings): a multi-worker deployment
would need a shared store (Redis, etc.) for every worker to see every in-flight
request's progress, not just the one handling it. Acceptable here since a stage
label is purely cosmetic - worst case on a multi-worker setup, an unlucky poll
just finds nothing yet and the UI holds its last-known text a beat longer, with
no effect on the actual answer.

Deliberately no-ops on a falsy request_id everywhere - older/malformed requests
that don't send one simply get no live progress, not an error.
'''

import time
from threading import Lock
from typing import Dict, Optional

_lock = Lock()
_progress: Dict[str, Dict[str, float]] = {}

# Long enough to outlast even a slow answer plus one client poll gap, short
# enough that an abandoned/crashed request's entry doesn't linger forever.
_TTL_SECONDS = 180


def start(request_id: Optional[str]) -> None:
    if not request_id:
        return
    with _lock:
        _progress[request_id] = {"stage": "Reading your question…", "updated_at": time.monotonic()}


def update(request_id: Optional[str], stage: str) -> None:
    if not request_id:
        return
    with _lock:
        if request_id in _progress:
            _progress[request_id] = {"stage": stage, "updated_at": time.monotonic()}


def get(request_id: str) -> Optional[str]:
    _evict_stale()
    with _lock:
        entry = _progress.get(request_id)
        return entry["stage"] if entry else None


def finish(request_id: Optional[str]) -> None:
    if not request_id:
        return
    with _lock:
        _progress.pop(request_id, None)


def _evict_stale() -> None:
    now = time.monotonic()
    with _lock:
        stale = [rid for rid, entry in _progress.items() if now - entry["updated_at"] > _TTL_SECONDS]
        for rid in stale:
            _progress.pop(rid, None)
