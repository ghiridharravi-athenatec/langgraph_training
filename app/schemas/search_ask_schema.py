from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SearchAskChatRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    # UI-facing Claude model choice ("haiku" | "sonnet" | "opus") - same mapping
    # as the document-chat /chat endpoint's `model` field.
    model: Optional[str] = None
    # Client-generated (crypto.randomUUID()) - same live-progress mechanism as
    # QAResponse.request_id (see app/core/progress.py). Optional and cosmetic only.
    request_id: Optional[str] = None


class SearchAskDocumentOut(BaseModel):
    '''Upload-only record - no chunk_count/extracted_text fields, since nothing here
    is ever extracted or chunked (see app/utils/mongo.py's search_ask_documents
    collection docstring).'''

    id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
