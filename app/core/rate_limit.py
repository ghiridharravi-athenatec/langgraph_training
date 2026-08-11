import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Depends, HTTPException, status

from app.core.logger import get_logger
from app.core.security import get_current_user

logger = get_logger(__name__)

# In-memory per-(user_id, scope) sliding window. Documented limitation: resets on
# restart and doesn't share state across multiple worker processes - acceptable for
# this app's single-process deployment, same honesty standard as the existing
# stateless-refresh-token tradeoff.
_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)


def _check_rate_limit(key: Tuple[str, str], max_requests: int, window_seconds: int) -> None:
    now = time.monotonic()
    window = _hits[key]

    while window and now - window[0] > window_seconds:
        window.popleft()

    if len(window) >= max_requests:
        retry_after = max(1, int(window_seconds - (now - window[0])))
        logger.warning("Rate limit exceeded for %s: %d requests in %ds", key, len(window), window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({max_requests} requests per {window_seconds}s). Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)


def rate_limit(scope: str, max_requests: int, window_seconds: int):
    '''Dependency factory: per-user sliding-window rate limit for a named scope
    (e.g. "chat", "ingest"). Runs after auth (needs current_user), so an
    unauthenticated/unauthorized request gets 401/403 rather than a misleading 429.'''

    def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        _check_rate_limit((current_user["_id"], scope), max_requests, window_seconds)
        return current_user

    return _dependency
