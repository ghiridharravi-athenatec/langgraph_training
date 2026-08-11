from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_project_access
from app.schemas.conversation_schema import ConversationOut, ConversationRename, MessageOut
from app.utils.mongo import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    rename_conversation,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Chat history lives behind the same project gate as /chat and /ingest - it's part of the
# ragchatbot project's data, not a general-purpose feature.
_require_ragchatbot_access = require_project_access("ragchatbot")


def _own_conversation_or_404(conversation_id: str, current_user: dict) -> dict:
    '''Ownership is checked independently of the ID itself - never trust a conversation_id
    supplied by the client to imply the caller may read/rename/delete it.'''
    conversation = get_conversation(conversation_id)
    if conversation is None or conversation["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def _to_out(conversation: dict) -> ConversationOut:
    return ConversationOut(
        id=conversation["_id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
    )


@router.get("", response_model=list[ConversationOut])
def get_conversations(current_user: dict = Depends(_require_ragchatbot_access)):
    return [_to_out(c) for c in list_conversations(current_user["_id"])]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_new_conversation(current_user: dict = Depends(_require_ragchatbot_access)):
    return _to_out(create_conversation(current_user["_id"]))


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def get_conversation_messages(conversation_id: str, current_user: dict = Depends(_require_ragchatbot_access)):
    _own_conversation_or_404(conversation_id, current_user)
    return [
        MessageOut(
            id=m["_id"],
            role=m["role"],
            content=m["content"],
            logs=m.get("logs"),
            graph_response=m.get("graph_response"),
            cached=m.get("cached"),
            blocked=m.get("blocked"),
            created_at=m["created_at"],
        )
        for m in list_messages(conversation_id)
    ]


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_existing_conversation(
    conversation_id: str, payload: ConversationRename, current_user: dict = Depends(_require_ragchatbot_access)
):
    _own_conversation_or_404(conversation_id, current_user)
    title = payload.title.strip()[:50] or "New chat"
    rename_conversation(conversation_id, title)
    return _to_out(get_conversation(conversation_id))


@router.delete("/{conversation_id}")
def delete_existing_conversation(conversation_id: str, current_user: dict = Depends(_require_ragchatbot_access)):
    _own_conversation_or_404(conversation_id, current_user)
    delete_conversation(conversation_id)
    return {"message": "Conversation deleted"}
