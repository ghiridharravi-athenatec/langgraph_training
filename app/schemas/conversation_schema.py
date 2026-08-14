from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


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
    created_at: datetime
