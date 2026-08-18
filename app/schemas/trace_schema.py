from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class TraceUserOut(BaseModel):
    id: str
    email: str
    role: str
    conversation_count: int


class TraceConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    blocked_count: int
    cached_count: int


class TraceMessageOut(BaseModel):
    id: str
    role: str
    content: str
    logs: Optional[List[Any]] = None
    graph_response: Optional[Any] = None
    # Only populated for database-chatbot messages - see TraceTurnOut.
    guardrail_events: Optional[List[Any]] = None
    cached: Optional[bool] = None
    blocked: Optional[bool] = None
    response_time_ms: Optional[float] = None
    created_at: datetime
    turn_id: Optional[str] = None


class TraceTurnOut(BaseModel):
    '''One request/response pair - a Langfuse-style trace row. Flat across every
    conversation the user has had, newest first.'''

    id: str
    conversation_id: str
    question: str
    answer: str
    created_at: datetime
    logs: Optional[List[Any]] = None
    graph_response: Optional[Any] = None
    # Only populated for database-chatbot turns - the agent's tool-call trace,
    # rendered as a ToolCallLog instead of the document pipeline's checklist.
    guardrail_events: Optional[List[Any]] = None
    cached: Optional[bool] = None
    blocked: Optional[bool] = None
    response_time_ms: Optional[float] = None
