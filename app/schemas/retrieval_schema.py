from typing import Any, List, Optional
from pydantic import BaseModel


class QAResponse(BaseModel):
    '''Length and blank-question checks are deliberately NOT enforced here via Pydantic -
    they're owned by guardrails.validate_input()'s own "length" check, so a too-short/too-long/blank
    question fails through the same guardrail pipeline (and shows up in the UI's guardrail
    checklist) instead of a raw, differently-shaped 422 validation error.'''
    question: str
    conversation_id: Optional[str] = None
    # Client-generated (crypto.randomUUID()) - lets the chat screen poll
    # GET /progress/{request_id} for a live "what's happening right now" label
    # while this request is in flight. Optional and purely cosmetic - omitting
    # it just means no live progress, never an error (see app/core/progress.py).
    request_id: Optional[str] = None
    # UI-facing Claude model choice ("haiku" | "sonnet" | "opus") - see the picker
    # next to the chat input. None/unrecognized falls back to CLAUDE_MODEL
    # (llm_provider.resolve_claude_model owns the mapping to a real model id).
    model: Optional[str] = None
    # Always overwritten server-side from the authenticated session right after auth
    # (see api.py's /chat handler) - never trust a client-supplied value here, since
    # it scopes which user's documents retrieval is allowed to search.
    user_id: str = ""
    # Prior (question, answer) turns from this conversation - always overwritten
    # server-side from Mongo right before the graph runs (see api.py's /chat
    # handler), same as user_id; never trust a client-supplied value here.
    history: List[Any] = []
    retrieved_chunks: List[Any] = []
    reranked_chunks: List[Any] = []
    context: str = ""
    answer: str = ""
    logs: List[Any] = []
    guardrail_events: List[Any] = []
    blocked: bool = False
    block_reason: Optional[str] = None
    token_count: int = 0