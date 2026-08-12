from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_project_access
from app.schemas.document_schema import DocumentDetailOut, DocumentOut
from app.utils.mongo import ROLE_ADMIN, get_document, get_user_by_id, list_documents, list_users, user_has_documents

# Document browsing lives behind the same project gate as /chat and /ingest - it's
# part of the ragchatbot project's data.
_require_ragchatbot_access = require_project_access("ragchatbot")

router = APIRouter(prefix="/documents", tags=["documents"])


def _is_admin(current_user: dict) -> bool:
    return current_user.get("role") == ROLE_ADMIN


def _to_out(doc: dict, uploaded_by: str = None) -> DocumentOut:
    return DocumentOut(
        id=doc["_id"],
        filename=doc["filename"],
        content_type=doc["content_type"],
        size_bytes=doc["size_bytes"],
        chunk_count=doc["chunk_count"],
        created_at=doc["created_at"],
        uploaded_by=uploaded_by,
    )


@router.get("", response_model=list[DocumentOut])
def get_documents(current_user: dict = Depends(_require_ragchatbot_access)):
    '''Admins see every user's ingested documents; everyone else sees only their own.'''
    if _is_admin(current_user):
        uploader_emails = {u["_id"]: u["email"] for u in list_users()}
        return [_to_out(d, uploaded_by=uploader_emails.get(d["user_id"])) for d in list_documents()]

    return [_to_out(d) for d in list_documents(user_id=current_user["_id"])]


@router.get("/status")
def get_documents_status(current_user: dict = Depends(_require_ragchatbot_access)):
    '''Drives the chat screen's empty-knowledge-base disclaimer. Scoped to the caller's
    own uploads, matching retrieval's per-user isolation - chat only ever searches this
    user's own chunks, so this must answer "does *my* chat have anything to draw on",
    not "has anyone, anywhere, ingested something". True for admins too.'''
    return {"has_documents": user_has_documents(current_user["_id"])}


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document_detail(document_id: str, current_user: dict = Depends(_require_ragchatbot_access)):
    doc = get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_admin = _is_admin(current_user)
    if not is_admin and doc["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    uploaded_by = None
    if is_admin:
        uploader = get_user_by_id(doc["user_id"])
        uploaded_by = uploader["email"] if uploader else None

    return DocumentDetailOut(
        id=doc["_id"],
        filename=doc["filename"],
        content_type=doc["content_type"],
        size_bytes=doc["size_bytes"],
        chunk_count=doc["chunk_count"],
        created_at=doc["created_at"],
        uploaded_by=uploaded_by,
        extracted_text=doc["extracted_text"],
    )
