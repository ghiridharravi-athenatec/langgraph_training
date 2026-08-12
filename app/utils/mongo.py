import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, ReturnDocument
from pymongo.operations import SearchIndexModel
from app.core import config
from app.core.logger import get_logger

logger = get_logger(__name__)

DB_NAME = "rag_database"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# Single unified vector-store collection every ingested document's chunks go into -
# general-purpose ingestion, not split by document category.
DOCUMENT_CHUNKS_COLLECTION = "document_chunks"


@lru_cache(maxsize=1)
def get_mongo_client():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    # tz_aware=True: BSON dates are stored as UTC but pymongo returns them naive by
    # default on read, which breaks any comparison against datetime.now(timezone.utc)
    # (see record_login_failure/get_login_lockout, which do exactly that).
    return MongoClient(mongo_uri, tz_aware=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_users_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["users"]


def get_projects_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["projects"]


def get_permissions_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["permissions"]


def get_login_attempts_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["login_attempts"]


def get_used_refresh_tokens_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["used_refresh_tokens"]


def get_usage_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["usage"]


def get_conversations_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["conversations"]


def get_messages_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["messages"]


def get_guardrail_config_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["guardrail_config"]


def get_documents_collection(db_name: str = DB_NAME):
    return get_mongo_client()[db_name]["documents"]


def user_has_documents(user_id: str, db_name: str = DB_NAME) -> bool:
    '''Per-user, matching retrieval's per-user isolation - chat only ever searches
    this user's own ingested chunks, so "does chat have anything to answer from" has
    to be answered per-user too, not globally (not even for an admin).'''
    return get_documents_collection(db_name).find_one({"user_id": user_id}, {"_id": 1}) is not None


def ensure_indexes(db_name: str = DB_NAME) -> None:
    get_users_collection(db_name).create_index("email", unique=True)
    get_projects_collection(db_name).create_index("enabled")
    get_permissions_collection(db_name).create_index(
        [("user_id", 1), ("project_id", 1)], unique=True
    )
    get_login_attempts_collection(db_name).create_index(
        "window_start", expireAfterSeconds=config.LOGIN_LOCKOUT_WINDOW_MINUTES * 60
    )
    get_used_refresh_tokens_collection(db_name).create_index(
        "used_at", expireAfterSeconds=config.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )
    get_usage_collection(db_name).create_index("created_at", expireAfterSeconds=7 * 86400)
    get_conversations_collection(db_name).create_index([("user_id", 1), ("updated_at", -1)])
    get_messages_collection(db_name).create_index([("conversation_id", 1), ("created_at", 1)])
    get_messages_collection(db_name).create_index([("user_id", 1), ("cached", 1)])
    get_documents_collection(db_name).create_index([("user_id", 1), ("created_at", -1)])
    logger.info(
        "Ensured indexes on users/projects/permissions/login_attempts/used_refresh_tokens/usage/"
        "conversations/messages/documents collections"
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(email: str, password_hash: str, role: str = ROLE_USER, db_name: str = DB_NAME) -> Dict[str, Any]:
    doc = {
        "_id": str(uuid.uuid4()),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "role": role,
        "token_version": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    get_users_collection(db_name).insert_one(doc)
    return doc


def bump_token_version(user_id: str, db_name: str = DB_NAME) -> Optional[int]:
    '''Invalidates every outstanding access/refresh token for this user - used when
    refresh-token reuse is detected (a signal of theft).'''
    doc = get_users_collection(db_name).find_one_and_update(
        {"_id": user_id},
        {"$inc": {"token_version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    return doc["token_version"] if doc else None


def get_user_by_email(email: str, db_name: str = DB_NAME) -> Optional[Dict[str, Any]]:
    return get_users_collection(db_name).find_one({"email": email.strip().lower()})


def get_user_by_id(user_id: str, db_name: str = DB_NAME) -> Optional[Dict[str, Any]]:
    return get_users_collection(db_name).find_one({"_id": user_id})


def list_users(db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    return list(get_users_collection(db_name).find({}))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(project_id: str, name: str, description: str = "", enabled: bool = True, db_name: str = DB_NAME) -> Dict[str, Any]:
    doc = {
        "_id": project_id,
        "name": name,
        "description": description,
        "enabled": enabled,
        "created_at": _now(),
        "updated_at": _now(),
    }
    get_projects_collection(db_name).insert_one(doc)
    return doc


def upsert_default_project(project_id: str, name: str, description: str = "", db_name: str = DB_NAME) -> None:
    '''Creates the project only if it doesn't already exist; never overwrites an existing one.'''
    get_projects_collection(db_name).update_one(
        {"_id": project_id},
        {
            "$setOnInsert": {
                "name": name,
                "description": description,
                "enabled": True,
                "created_at": _now(),
                "updated_at": _now(),
            }
        },
        upsert=True,
    )


def get_project(project_id: str, db_name: str = DB_NAME) -> Optional[Dict[str, Any]]:
    return get_projects_collection(db_name).find_one({"_id": project_id})


def list_projects(only_enabled: bool = False, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    query = {"enabled": True} if only_enabled else {}
    return list(get_projects_collection(db_name).find(query))


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def list_permitted_project_ids(user_id: str, db_name: str = DB_NAME) -> List[str]:
    return [p["project_id"] for p in get_permissions_collection(db_name).find({"user_id": user_id})]


def has_permission(user_id: str, project_id: str, db_name: str = DB_NAME) -> bool:
    return get_permissions_collection(db_name).find_one({"user_id": user_id, "project_id": project_id}) is not None


def set_user_permissions(user_id: str, project_ids: List[str], db_name: str = DB_NAME) -> None:
    '''Replaces the full set of project grants for a user with project_ids (idempotent, no duplicates).'''
    collection = get_permissions_collection(db_name)
    desired = set(project_ids)
    current = set(list_permitted_project_ids(user_id, db_name))

    to_add = desired - current
    to_remove = current - desired

    for project_id in to_add:
        collection.update_one(
            {"user_id": user_id, "project_id": project_id},
            {"$setOnInsert": {"_id": str(uuid.uuid4()), "created_at": _now()}},
            upsert=True,
        )
    if to_remove:
        collection.delete_many({"user_id": user_id, "project_id": {"$in": list(to_remove)}})


def list_all_permissions(db_name: str = DB_NAME) -> Dict[str, List[str]]:
    '''Returns {user_id: [project_id, ...]} for every user with at least one grant.'''
    result: Dict[str, List[str]] = {}
    for perm in get_permissions_collection(db_name).find({}):
        result.setdefault(perm["user_id"], []).append(perm["project_id"])
    return result


# ---------------------------------------------------------------------------
# Login lockout
# ---------------------------------------------------------------------------

def record_login_failure(email: str, db_name: str = DB_NAME) -> Dict[str, Any]:
    '''Increments the failure count for a sliding window; locks the account once
    LOGIN_LOCKOUT_THRESHOLD is hit within LOGIN_LOCKOUT_WINDOW_MINUTES.'''
    email = email.strip().lower()
    collection = get_login_attempts_collection(db_name)
    now = _now()
    doc = collection.find_one({"_id": email})

    window_expired = doc is None or (now - doc["window_start"]).total_seconds() > config.LOGIN_LOCKOUT_WINDOW_MINUTES * 60
    count = 1 if window_expired else doc["count"] + 1
    window_start = now if window_expired else doc["window_start"]
    locked_until = now + timedelta(minutes=config.LOGIN_LOCKOUT_WINDOW_MINUTES) if count >= config.LOGIN_LOCKOUT_THRESHOLD else None

    collection.update_one(
        {"_id": email},
        {"$set": {"count": count, "window_start": window_start, "locked_until": locked_until}},
        upsert=True,
    )
    return {"count": count, "locked_until": locked_until}


def reset_login_attempts(email: str, db_name: str = DB_NAME) -> None:
    get_login_attempts_collection(db_name).delete_one({"_id": email.strip().lower()})


def get_login_lockout(email: str, db_name: str = DB_NAME) -> Optional[datetime]:
    '''Returns the lockout expiry if the account is currently locked, else None.'''
    doc = get_login_attempts_collection(db_name).find_one({"_id": email.strip().lower()})
    if doc and doc.get("locked_until") and doc["locked_until"] > _now():
        return doc["locked_until"]
    return None


# ---------------------------------------------------------------------------
# Refresh-token reuse detection
# ---------------------------------------------------------------------------

def is_refresh_jti_used(jti: str, db_name: str = DB_NAME) -> bool:
    return get_used_refresh_tokens_collection(db_name).find_one({"_id": jti}) is not None


def mark_refresh_jti_used(jti: str, db_name: str = DB_NAME) -> None:
    get_used_refresh_tokens_collection(db_name).update_one(
        {"_id": jti}, {"$setOnInsert": {"used_at": _now()}}, upsert=True
    )


# ---------------------------------------------------------------------------
# Token usage / quota
# ---------------------------------------------------------------------------

def get_daily_usage(user_id: str, date_str: str, db_name: str = DB_NAME) -> int:
    doc = get_usage_collection(db_name).find_one({"_id": f"{user_id}:{date_str}"})
    return doc["tokens_used"] if doc else 0


def increment_usage(user_id: str, date_str: str, tokens: int, db_name: str = DB_NAME) -> None:
    if tokens <= 0:
        return
    get_usage_collection(db_name).update_one(
        {"_id": f"{user_id}:{date_str}"},
        {
            "$inc": {"tokens_used": tokens},
            "$setOnInsert": {"user_id": user_id, "date": date_str, "created_at": _now()},
        },
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Conversations & messages (chat history + same-user semantic cache index)
# ---------------------------------------------------------------------------

MAX_CONVERSATION_TITLE_LENGTH = 50


def create_conversation(user_id: str, db_name: str = DB_NAME) -> Dict[str, Any]:
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": "New chat",
        "created_at": _now(),
        "updated_at": _now(),
    }
    get_conversations_collection(db_name).insert_one(doc)
    return doc


def get_conversation(conversation_id: str, db_name: str = DB_NAME) -> Optional[Dict[str, Any]]:
    return get_conversations_collection(db_name).find_one({"_id": conversation_id})


def list_conversations(user_id: str, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    return list(get_conversations_collection(db_name).find({"user_id": user_id}).sort("updated_at", -1))


def rename_conversation(conversation_id: str, title: str, db_name: str = DB_NAME) -> None:
    get_conversations_collection(db_name).update_one(
        {"_id": conversation_id}, {"$set": {"title": title, "updated_at": _now()}}
    )


def delete_conversation(conversation_id: str, db_name: str = DB_NAME) -> None:
    get_messages_collection(db_name).delete_many({"conversation_id": conversation_id})
    get_conversations_collection(db_name).delete_one({"_id": conversation_id})


def touch_conversation(conversation_id: str, first_question: Optional[str] = None, db_name: str = DB_NAME) -> None:
    '''Bumps updated_at (so the sidebar list sorts by recency) and, the first time a question
    lands on a still-untitled conversation, derives the title from it.'''
    collection = get_conversations_collection(db_name)
    updates: Dict[str, Any] = {"updated_at": _now()}

    if first_question:
        conversation = collection.find_one({"_id": conversation_id})
        if conversation and conversation.get("title") == "New chat":
            trimmed = first_question.strip()
            title = trimmed[:MAX_CONVERSATION_TITLE_LENGTH]
            if len(trimmed) > MAX_CONVERSATION_TITLE_LENGTH:
                title += "..."
            updates["title"] = title

    collection.update_one({"_id": conversation_id}, {"$set": updates})


def add_message(conversation_id: str, user_id: str, role: str, content: str, db_name: str = DB_NAME, **extra) -> Dict[str, Any]:
    doc = {
        "_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "created_at": _now(),
        **extra,
    }
    get_messages_collection(db_name).insert_one(doc)
    return doc


def list_messages(conversation_id: str, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    return list(get_messages_collection(db_name).find({"conversation_id": conversation_id}).sort("created_at", 1))


def list_users_with_conversation_counts(db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    '''All users, each annotated with conversation_count - one aggregation for the counts
    rather than a query per user.'''
    users = list_users(db_name)
    counts = {
        row["_id"]: row["count"]
        for row in get_conversations_collection(db_name).aggregate(
            [{"$group": {"_id": "$user_id", "count": {"$sum": 1}}}]
        )
    }
    for user in users:
        user["conversation_count"] = counts.get(user["_id"], 0)
    return users


def list_conversations_with_message_counts(user_id: str, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    '''A user's conversations, each annotated with message/blocked/cached counts - one
    aggregation for all three rather than a query per conversation.'''
    conversations = list_conversations(user_id, db_name)
    if not conversations:
        return conversations

    conversation_ids = [c["_id"] for c in conversations]
    stats = {
        row["_id"]: row
        for row in get_messages_collection(db_name).aggregate(
            [
                {"$match": {"conversation_id": {"$in": conversation_ids}}},
                {
                    "$group": {
                        "_id": "$conversation_id",
                        "count": {"$sum": 1},
                        "blocked_count": {"$sum": {"$cond": [{"$eq": ["$blocked", True]}, 1, 0]}},
                        "cached_count": {"$sum": {"$cond": [{"$eq": ["$cached", True]}, 1, 0]}},
                    }
                },
            ]
        )
    }
    for conversation in conversations:
        row = stats.get(conversation["_id"], {})
        conversation["message_count"] = row.get("count", 0)
        conversation["blocked_count"] = row.get("blocked_count", 0)
        conversation["cached_count"] = row.get("cached_count", 0)
    return conversations


def list_user_turns(user_id: str, limit: int = 200, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    '''Flat list of Q&A turns across every conversation this user has had, newest
    first - a Langfuse-style trace list (one row per request) rather than
    grouped by conversation. Pairs each "user" message with the "assistant"
    message that immediately follows it in the same conversation, since
    that's where the guardrail trace (graph_response, blocked, cached)
    actually lives - the user message is just the question text.'''
    messages = list(
        get_messages_collection(db_name)
        .find({"user_id": user_id})
        .sort([("conversation_id", 1), ("created_at", 1)])
    )

    turns: List[Dict[str, Any]] = []
    pending_question: Optional[Dict[str, Any]] = None
    for message in messages:
        if message["role"] == "user":
            pending_question = message
        elif message["role"] == "assistant" and pending_question is not None:
            turns.append({
                "_id": pending_question["_id"],
                "conversation_id": message["conversation_id"],
                "question": pending_question["content"],
                "answer": message["content"],
                "created_at": pending_question["created_at"],
                "logs": message.get("logs"),
                "graph_response": message.get("graph_response"),
                "cached": message.get("cached"),
                "blocked": message.get("blocked"),
                "response_time_ms": message.get("response_time_ms"),
            })
            pending_question = None

    turns.sort(key=lambda t: t["created_at"], reverse=True)
    return turns[:limit]


def list_cache_candidates(user_id: str, limit: int, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    '''Fresh, successfully-generated, non-cached assistant answers for this user - the only
    messages eligible to be reused for a future similar question. A cached answer never itself
    becomes a cache candidate (no embedding is stored for it), so cache hits can't chain off
    other cache hits and drift away from the original question over time.'''
    return list(
        get_messages_collection(db_name)
        .find({
            "user_id": user_id,
            "role": "assistant",
            "cached": False,
            "blocked": False,
            "question_embedding": {"$exists": True, "$ne": None},
        })
        .sort("created_at", -1)
        .limit(limit)
    )


# ---------------------------------------------------------------------------
# Guardrail config (admin-editable thresholds/lists - see app/core/guardrail_config.py)
# ---------------------------------------------------------------------------

GUARDRAIL_CONFIG_ID = "default"


def get_guardrail_config_doc(db_name: str = DB_NAME) -> Dict[str, Any]:
    doc = get_guardrail_config_collection(db_name).find_one({"_id": GUARDRAIL_CONFIG_ID})
    if not doc:
        return {}
    return {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}


def set_guardrail_config_doc(patch: Dict[str, Any], db_name: str = DB_NAME) -> Dict[str, Any]:
    get_guardrail_config_collection(db_name).update_one(
        {"_id": GUARDRAIL_CONFIG_ID},
        {"$set": {**patch, "updated_at": _now()}},
        upsert=True,
    )
    return get_guardrail_config_doc(db_name)


def reset_guardrail_config_doc(defaults: Dict[str, Any], db_name: str = DB_NAME) -> Dict[str, Any]:
    get_guardrail_config_collection(db_name).replace_one(
        {"_id": GUARDRAIL_CONFIG_ID},
        {"_id": GUARDRAIL_CONFIG_ID, **defaults, "updated_at": _now()},
        upsert=True,
    )
    return get_guardrail_config_doc(db_name)


# ---------------------------------------------------------------------------
# Ingested-document tracking (for the per-user "Documents" tab) - separate from
# DOCUMENT_CHUNKS_COLLECTION, which holds the embedded chunks used for retrieval.
# One record per uploaded file: who uploaded it, and its extracted (PII-masked)
# text for the read-only viewer.
# ---------------------------------------------------------------------------

def create_document_record(
    user_id: str, filename: str, content_type: str, size_bytes: int,
    extracted_text: str, chunk_count: int, db_name: str = DB_NAME,
) -> Dict[str, Any]:
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "extracted_text": extracted_text,
        "chunk_count": chunk_count,
        "created_at": _now(),
    }
    get_documents_collection(db_name).insert_one(doc)
    return doc


def list_documents(user_id: Optional[str] = None, db_name: str = DB_NAME) -> List[Dict[str, Any]]:
    '''user_id=None returns every user's documents (the admin view); a user_id scopes to
    that user's own uploads only.'''
    query = {} if user_id is None else {"user_id": user_id}
    return list(get_documents_collection(db_name).find(query).sort("created_at", -1))


def get_document(document_id: str, db_name: str = DB_NAME) -> Optional[Dict[str, Any]]:
    return get_documents_collection(db_name).find_one({"_id": document_id})


def create_vector_search_index(collection_name: str, db_name: str = "rag_database"):
    client = get_mongo_client()
    collection = client[db_name][collection_name]

    # user_id is a filter field, not just metadata: retrieval scopes every search to
    # the requesting user's own chunks only (see retrieve.py's pre_filter), and Atlas
    # Vector Search requires a field to be declared filterable in the index before a
    # query can filter on it.
    definition = {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine"},
            {"type": "filter", "path": "source"},
            {"type": "filter", "path": "user_id"},
        ]
    }

    try:
        existing_indexes = list(collection.list_search_indexes())
    except Exception as e:
        # Depending on MongoDB version or permissions, listing might fail before an index is created
        logger.warning("Could not list existing search indexes for '%s': %s", collection_name, e)
        existing_indexes = []

    existing = next((idx for idx in existing_indexes if idx.get("name") == "default"), None)

    if existing is not None:
        existing_paths = {f.get("path") for f in (existing.get("latestDefinition") or {}).get("fields", [])}
        if "user_id" in existing_paths:
            logger.info("Search index 'default' already exists on '%s' and is up to date.", collection_name)
            return
        # Index predates per-user retrieval isolation - add the missing filter field.
        # Idempotent, and only actually triggers a rebuild the first time this runs.
        try:
            collection.update_search_index(name="default", definition=definition)
            logger.info("Updated search index 'default' on '%s' to add the user_id filter field.", collection_name)
        except Exception as e:
            logger.exception("Failed to update search index on '%s' with user_id filter: %s", collection_name, e)
        return

    search_index_model = SearchIndexModel(definition=definition, name="default", type="vectorSearch")

    try:
        collection.create_search_index(model=search_index_model)
        logger.info("Successfully initiated creation of vector search index 'default' on '%s'.", collection_name)
    except Exception as e:
        logger.exception("Failed to create search index on '%s': %s", collection_name, e)
