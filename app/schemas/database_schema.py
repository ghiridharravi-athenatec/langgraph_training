from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ENGINE_LITERAL = Literal["postgresql", "mysql", "mssql", "mongodb"]


class DatabaseConnectionCreate(BaseModel):
    '''Accepts EITHER connection_string OR the structured host/username/database
    fields (whichever the "Database Ingestion" form's user filled in) - see
    app/core/db_connections.py's build_connection_details for how these get
    normalized into one internal spec per engine.'''

    name: str
    engine: ENGINE_LITERAL
    connection_string: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None

    @model_validator(mode="after")
    def _one_of_connection_string_or_fields(self):
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if self.connection_string:
            return self
        if not all([self.host, self.username, self.database]):
            raise ValueError("Provide either connection_string, or at least host/username/database.")
        return self


class DatabaseConnectionOut(BaseModel):
    '''Never includes credentials - password/connection_string never leave
    app/core/db_connections.py's encrypted storage once saved.'''

    id: str
    name: str
    engine: str
    database: str
    host: Optional[str] = None
    created_at: datetime


class DatabaseChatRequest(BaseModel):
    connection_id: str
    question: str
    conversation_id: Optional[str] = None
    # UI-facing Claude model choice ("haiku" | "sonnet" | "opus") - same mapping
    # as the document-chat /chat endpoint's `model` field.
    model: Optional[str] = None
    # Client-generated (crypto.randomUUID()) - same live-progress mechanism as
    # QAResponse.request_id (see app/core/progress.py). Optional and cosmetic only.
    request_id: Optional[str] = None
