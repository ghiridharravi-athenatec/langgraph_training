import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core import config, db_connections, guardrail_config, progress
from app.core.db_agent import run_db_agent
from app.core.guardrails_agent import guardrails_agent
from app.core.logger import get_logger
from app.core.messages import msg
from app.core.rate_limit import rate_limit
from app.core.security import require_project_access
from app.core.streaming import stream_answer
from app.schemas.database_schema import DatabaseChatRequest, DatabaseConnectionCreate, DatabaseConnectionOut
from app.utils.mongo import (
    add_message,
    create_conversation,
    create_database_connection,
    delete_database_connection,
    get_conversation,
    get_conversation_history,
    get_daily_usage,
    get_database_connection,
    increment_usage,
    list_database_connections,
    touch_conversation,
    update_database_connection,
)

logger = get_logger(__name__)

# The database chatbot's own project - separate from ragchatbot (the document
# chatbot). Connections, chat, and conversation history all live behind this
# one grant.
_require_database_chatbot_access = require_project_access("database-chatbot")
_db_chat_rate_limit = rate_limit("db_chat", config.CHAT_RATE_LIMIT, config.RATE_LIMIT_WINDOW_SECONDS)

router = APIRouter(prefix="/database", tags=["database"])


def _to_out(doc: dict) -> DatabaseConnectionOut:
    return DatabaseConnectionOut(
        id=doc["_id"], name=doc["name"], engine=doc["engine"], database=doc["database"],
        host=doc.get("host"), created_at=doc["created_at"],
    )


def _get_owned_connection(connection_id: str, user_id: str, not_found_detail: str = "Database connection not found") -> dict:
    '''Deliberately owner-only, no admin override - unlike documents, a saved DB
    connection's mere existence (host, engine, which database) is sensitive on its
    own even without exposing the credentials, so this doesn't get the same
    admin-sees-everyone's pattern app/api/v1/documents.py uses.

    not_found_detail lets chat_with_database give a more actionable message than
    the connections CRUD endpoints need - an old conversation pinned to a
    since-deleted connection is a normal, recoverable situation (start a new
    chat), not just "that id doesn't exist".'''
    connection = get_database_connection(connection_id)
    if connection is None or connection["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return connection


@router.get("/connections", response_model=list[DatabaseConnectionOut])
def get_connections(current_user: dict = Depends(_require_database_chatbot_access)):
    return [_to_out(c) for c in list_database_connections(user_id=current_user["_id"])]


def _build_and_validate_details(payload: DatabaseConnectionCreate) -> dict:
    try:
        details = db_connections.build_connection_details(
            engine=payload.engine, connection_string=payload.connection_string, host=payload.host,
            port=payload.port, username=payload.username, password=payload.password, database=payload.database,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Validate by actually connecting and listing tables before ever saving anything -
    # same "prove it works before persisting" spirit as document ingestion's
    # file-type/size checks, just for a connection instead of a file.
    try:
        db_connections.test_connection(details)
    except db_connections.ConnectionError_ as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not connect: {e}")

    return details


@router.post("/connections", response_model=DatabaseConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(payload: DatabaseConnectionCreate, current_user: dict = Depends(_require_database_chatbot_access)):
    details = _build_and_validate_details(payload)
    encrypted = db_connections.encrypt_connection_details(details)
    doc = create_database_connection(
        user_id=current_user["_id"], name=payload.name, engine=payload.engine,
        encrypted_details=encrypted, database=details.get("database", ""), host=details.get("host"),
    )
    logger.info("User %s connected a %s database ('%s')", current_user["email"], payload.engine, payload.name)
    return _to_out(doc)


@router.put("/connections/{connection_id}", response_model=DatabaseConnectionOut)
def edit_connection(
    connection_id: str, payload: DatabaseConnectionCreate, current_user: dict = Depends(_require_database_chatbot_access),
):
    '''Full replacement, not a partial patch - re-validated and re-encrypted the same
    way a new connection is, since DatabaseConnectionOut never returns the existing
    password/connection_string/port/username for the client to prefill and resubmit
    unchanged. Conversations already chatting with this connection keep working -
    they reference it by id, not a snapshot of its details.'''
    _get_owned_connection(connection_id, current_user["_id"])
    details = _build_and_validate_details(payload)
    encrypted = db_connections.encrypt_connection_details(details)
    doc = update_database_connection(
        connection_id, name=payload.name, engine=payload.engine,
        encrypted_details=encrypted, database=details.get("database", ""), host=details.get("host"),
    )
    logger.info("User %s updated database connection '%s'", current_user["email"], payload.name)
    return _to_out(doc)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_connection(connection_id: str, current_user: dict = Depends(_require_database_chatbot_access)):
    _get_owned_connection(connection_id, current_user["_id"])
    delete_database_connection(connection_id)
    logger.info("User %s removed database connection %s", current_user["email"], connection_id)


def _persist_and_respond(
    conversation_id: str, user_id: str, question: str, answer: str, blocked: bool,
    guardrail_events: list, logs: list, start_time: float, message: str,
) -> dict:
    response_time_ms = round((time.perf_counter() - start_time) * 1000, 1)
    question_message = add_message(conversation_id, user_id, "user", question)
    add_message(
        conversation_id, user_id, "assistant", answer,
        question=question, logs=logs, blocked=blocked, response_time_ms=response_time_ms,
        guardrail_events=guardrail_events, turn_id=question_message["_id"],
    )
    touch_conversation(conversation_id, first_question=question)
    return {
        "message": message,
        "answer": answer,
        "logs": logs,
        "guardrail_events": guardrail_events,
        "conversation_id": conversation_id,
        "response_time_ms": response_time_ms,
        # Same id TraceTurnOut.id/GET /traces/turns/{turn_id} use for this turn -
        # lets the chat screen's "View Trace" link deep-link straight to it.
        "turn_id": question_message["_id"],
    }


def _generate_database_chat_response(payload: DatabaseChatRequest, current_user: dict) -> dict:
    '''Everything /database/chat used to do directly - unchanged. Split out so the
    route handler below can stream the finished, already-guardrail-checked response
    back in chunks (see app/core/streaming.py) instead of returning it all at once.'''
    start = time.perf_counter()
    progress.start(payload.request_id)
    try:
        if payload.conversation_id:
            conversation = get_conversation(payload.conversation_id)
            if (
                conversation is None
                or conversation["user_id"] != current_user["_id"]
                or conversation.get("project_id") != "database-chatbot"
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            conversation_id = conversation["_id"]
            # Pinned to whichever connection this conversation was started against -
            # never let a later message silently switch databases mid-conversation,
            # even if the client sends a different connection_id (falls back to the
            # payload's own value only for conversations that predate this field).
            connection_id = conversation.get("connection_id") or payload.connection_id
        else:
            conversation_id = None  # created below, once the connection is confirmed valid
            connection_id = payload.connection_id

        connection = _get_owned_connection(
            connection_id, current_user["_id"],
            not_found_detail=(
                "This conversation's database connection has been deleted - start a new chat and pick an "
                "active connection."
            ),
        )

        if conversation_id is None:
            conversation_id = create_conversation(current_user["_id"], "database-chatbot", connection_id=connection_id)["_id"]

        # Same input guardrail (length/prompt-injection/blocked-keyword checks) the
        # document chatbot applies before it does anything else - a database question
        # deserves the same screening a document question gets.
        progress.update(payload.request_id, "Guardrails Agent: validating your question…")
        input_check = guardrails_agent.check_input(payload.question)
        if not input_check["passed"]:
            logger.warning("Database chat request blocked by input guardrail: %s", input_check["reason"])
            return _persist_and_respond(
                conversation_id, current_user["_id"], payload.question,
                msg("common.blocked_prefix", reason=input_check["reason"]), True, [input_check],
                [f"[guardrail:input_validation] BLOCKED - {input_check['reason']}"], start,
                "Request blocked by input validation",
            )
        question = input_check["sanitized_question"]

        # Same daily-quota rule the document chatbot enforces, applied to this user's
        # combined usage across both chatbots (increment_usage/get_daily_usage are
        # shared, not scoped per-project) - exceeding quota on one blocks the other too.
        daily_usage = get_daily_usage(current_user["_id"], date.today().isoformat())
        daily_quota = current_user.get("daily_token_quota")
        if daily_quota is None:
            daily_quota = guardrail_config.get_config()["daily_token_quota"]
        progress.update(payload.request_id, "Guardrails Agent: checking your quota…")
        quota_event = guardrails_agent.check_quota(daily_usage, daily_quota)
        if not quota_event["passed"]:
            logger.warning("Database chat request blocked by quota guardrail: %s", quota_event["reason"])
            return _persist_and_respond(
                conversation_id, current_user["_id"], question,
                msg("common.blocked_prefix", reason=quota_event["reason"]), True, [input_check, quota_event],
                [f"[guardrail:quota_check] BLOCKED - {quota_event['reason']}"], start,
                "Request blocked by quota",
            )

        details = db_connections.decrypt_connection_details(connection["encrypted_details"])
        history = get_conversation_history(conversation_id, config.CHAT_HISTORY_MAX_TURNS)

        progress.update(payload.request_id, "Database Agent: inspecting the database…")
        result = run_db_agent(question, details, model=payload.model, history=history, request_id=payload.request_id)
        logger.info("Database chat answered for %s against connection '%s'", current_user["email"], connection["name"])

        increment_usage(current_user["_id"], date.today().isoformat(), result.get("token_count", 0))

        # Same output guardrail the document chatbot applies to its answers - a query
        # result can just as easily contain real PII (names, emails, phone numbers in a
        # table) as an ingested document can, so it gets the same blocked-keyword/PII
        # masking pass before ever reaching the user.
        progress.update(payload.request_id, "Guardrails Agent: checking the answer…")
        output_event = guardrails_agent.check_output(result["answer"])
        blocked = not output_event["passed"]
        answer = output_event["sanitized_answer"] if output_event["passed"] else msg("output_validation.blocked_answer")

        return _persist_and_respond(
            conversation_id, current_user["_id"], question, answer, blocked,
            [input_check, quota_event] + result["guardrail_events"] + [output_event],
            result["logs"], start, "Chat completed successfully",
        )
    finally:
        progress.finish(payload.request_id)


@router.post("/chat")
def chat_with_database(
    payload: DatabaseChatRequest,
    current_user: dict = Depends(_require_database_chatbot_access),
    _rate_limit_check: dict = Depends(_db_chat_rate_limit),
):
    response = _generate_database_chat_response(payload, current_user)
    return StreamingResponse(
        stream_answer(response),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
