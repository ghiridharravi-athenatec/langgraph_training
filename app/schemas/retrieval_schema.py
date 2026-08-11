from typing import Any, List, Optional
from pydantic import BaseModel


class QAResponse(BaseModel):
    '''Length and blank-question checks are deliberately NOT enforced here via Pydantic -
    they're owned by guardrails.validate_input()'s own "length" check, so a too-short/too-long/blank
    question fails through the same guardrail pipeline (and shows up in the UI's guardrail
    checklist) instead of a raw, differently-shaped 422 validation error.'''
    collection_name: str = "default"
    question: str
    conversation_id: Optional[str] = None
    retrieved_chunks: List[Any] = []
    reranked_chunks: List[Any] = []
    context: str = ""
    answer: str = ""
    logs: List[Any] = []
    guardrail_events: List[Any] = []
    blocked: bool = False
    block_reason: Optional[str] = None
    token_count: int = 0