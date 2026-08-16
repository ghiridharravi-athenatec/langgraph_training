from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    # Only ever set for database-chatbot conversations - the connection this
    # conversation is pinned to (see app/api/v1/database.py's POST /database/chat).
    connection_id: Optional[str] = None


class ConversationRename(BaseModel):
    title: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    logs: Optional[List[Any]] = None
    graph_response: Optional[Any] = None
    cached: Optional[bool] = None
    blocked: Optional[bool] = None
    response_time_ms: Optional[float] = None
    # Only populated for database-chatbot messages - the agent's tool-call trace
    # (which tables/queries it ran) plus any blocking guardrail events for that turn.
    guardrail_events: Optional[List[Any]] = None
    created_at: datetime
