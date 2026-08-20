'''Shared "stream an already-computed response back in small text chunks" helper,
used by both POST /chat and POST /database/chat once their response dict is fully
ready - i.e. after it's already been through every guardrail check exactly as
before this existed (PII masking, groundedness, compliance, the works).

Deliberately NOT raw token streaming during generation: this pipeline's output
guardrails can still block or rewrite the whole answer *after* it's generated
(groundedness, compliance, PII masking), so streaming live model tokens would
risk showing content that then gets retracted or replaced. This streams the
already-validated, already-masked final text instead - purely a delivery-pacing
effect (a typewriter reveal on the frontend), not a change to what's shown or
when it's safe to show it.
'''

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from app.core.guardrails import simplify_pii_tokens

_CHUNK_SIZE = 5  # characters per SSE delta - small enough to read as a typewriter reveal
_CHUNK_DELAY_SECONDS = 0.03


async def stream_answer(response: Dict[str, Any]) -> AsyncGenerator[str, None]:
    # simplify_pii_tokens collapses [[PII:TYPE:token]] down to "PII:TYPE" before
    # anything is sent - chunking the raw encrypted token character-by-character
    # would flash the ciphertext on screen for the ~1s it takes to stream in, only
    # collapsing once the closing "]]" completes the client's regex match. The
    # already-persisted Mongo record (see api.py - _persist_turn runs before this)
    # keeps the original response dict, encrypted token and all, untouched.
    answer = simplify_pii_tokens(response.get("answer") or "")
    for i in range(0, len(answer), _CHUNK_SIZE):
        yield f"data: {json.dumps({'type': 'delta', 'text': answer[i:i + _CHUNK_SIZE]})}\n\n"
        await asyncio.sleep(_CHUNK_DELAY_SECONDS)
    # Everything else the client needs (conversation_id, turn_id, logs,
    # graph_response/guardrail_events, response_time_ms, ...) in one final frame -
    # default=str as a defensive catch-all for anything not natively JSON-safe.
    # "answer" is overridden with the same simplified text the deltas already
    # streamed, not response["answer"] - the raw encrypted token has no reason to
    # ever reach the client, over SSE or otherwise.
    yield f"data: {json.dumps({**response, 'answer': answer, 'type': 'done'}, default=str)}\n\n"
