from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_project_access
from app.schemas.trace_schema import TraceConversationOut, TraceMessageOut, TraceTurnOut, TraceUserOut
from app.utils.mongo import (
    ROLE_ADMIN,
    get_conversation,
    get_user_by_id,
    list_conversations_with_message_counts,
    list_messages,
    list_user_turns,
    list_users_with_conversation_counts,
)

# A project like any other ("ragchatbot"'s sibling) - access is granted per-user via
# the same permissions table, not hardcoded to admins. Holding this grant lets a user
# view tracing data - but whose data depends on role (see _ensure_self_or_admin
# below): admins see everyone's, everyone else sees only their own.
_require_traces_access = require_project_access("guardrail-traces")

router = APIRouter(prefix="/traces", tags=["traces"], dependencies=[Depends(_require_traces_access)])


def _ensure_self_or_admin(current_user: dict, owner_user_id: str) -> None:
    if current_user.get("role") != ROLE_ADMIN and current_user["_id"] != owner_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own tracing data")


@router.get("/users", response_model=list[TraceUserOut])
def list_traced_users(current_user: dict = Depends(_require_traces_access)):
    users = list_users_with_conversation_counts()
    if current_user.get("role") != ROLE_ADMIN:
        users = [u for u in users if u["_id"] == current_user["_id"]]
    return [
        TraceUserOut(id=u["_id"], email=u["email"], role=u["role"], conversation_count=u["conversation_count"])
        for u in users
    ]


@router.get("/users/{user_id}/conversations", response_model=list[TraceConversationOut])
def list_user_conversations(user_id: str, current_user: dict = Depends(_require_traces_access)):
    _ensure_self_or_admin(current_user, user_id)
    if get_user_by_id(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return [
        TraceConversationOut(
            id=c["_id"],
            title=c["title"],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
            message_count=c["message_count"],
            blocked_count=c["blocked_count"],
            cached_count=c["cached_count"],
        )
        for c in list_conversations_with_message_counts(user_id)
    ]


@router.get("/users/{user_id}/turns", response_model=list[TraceTurnOut])
def list_user_trace_turns(user_id: str, current_user: dict = Depends(_require_traces_access)):
    '''Flat, Langfuse-style trace list: every question this user has asked, newest
    first, across all of their conversations.'''
    _ensure_self_or_admin(current_user, user_id)
    if get_user_by_id(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return [
        TraceTurnOut(
            id=t["_id"],
            conversation_id=t["conversation_id"],
            question=t["question"],
            answer=t["answer"],
            created_at=t["created_at"],
            logs=t.get("logs"),
            graph_response=t.get("graph_response"),
            cached=t.get("cached"),
            blocked=t.get("blocked"),
            response_time_ms=t.get("response_time_ms"),
        )
        for t in list_user_turns(user_id)
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[TraceMessageOut])
def get_conversation_trace(conversation_id: str, current_user: dict = Depends(_require_traces_access)):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    _ensure_self_or_admin(current_user, conversation["user_id"])
    return [
        TraceMessageOut(
            id=m["_id"],
            role=m["role"],
            content=m["content"],
            logs=m.get("logs"),
            graph_response=m.get("graph_response"),
            cached=m.get("cached"),
            blocked=m.get("blocked"),
            response_time_ms=m.get("response_time_ms"),
            created_at=m["created_at"],
        )
        for m in list_messages(conversation_id)
    ]
