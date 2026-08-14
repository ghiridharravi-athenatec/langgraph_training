from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    chunk_count: int
    created_at: datetime
    uploaded_by: Optional[str] = None  # uploader's email - only populated for the admin all-users view


class DocumentDetailOut(DocumentOut):
    extracted_text: str
