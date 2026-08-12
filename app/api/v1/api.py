import asyncio
import concurrent.futures
import time
from datetime import date
from fastapi import FastAPI, APIRouter, Depends
from fastapi import UploadFile, File, HTTPException
from pathlib import Path
import uuid, os
from app.utils.mongo import (
    ROLE_ADMIN,
    add_message,
    create_conversation,
    create_document_record,
    get_conversation,
    get_daily_usage,
    increment_usage,
    touch_conversation,
    user_has_documents,
)
from app.schemas.retrieval_schema import QAResponse
from app.utils.llm import IntentClassifier
from dotenv import load_dotenv
from app.utils.retrieve import compiled_graph, embedding_model, invalidate_bm25_cache
from app.core import config
from app.core.logger import get_logger
from app.core.guardrails import validate_input, validate_has_documents, evaluate_intent_detection, validate_quota
from app.core.ingest_guardrails import validate_file_size, validate_file_type
from app.core.rate_limit import rate_limit
from app.core.security import require_project_access
from app.core.semantic_cache import find_cache_match
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.projects import router as projects_router
from app.api.v1.traces import router as traces_router
from app.api.v1.guardrail_settings import router as guardrail_settings_router

router = APIRouter()
load_dotenv()
logger = get_logger(__name__)

router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(conversations_router)
router.include_router(documents_router)
router.include_router(projects_router)
router.include_router(traces_router)
router.include_router(guardrail_settings_router)

app = FastAPI(title="My FastAPI App")
absolute_path = os.path.abspath(".")
UPLOAD_DIR = Path(absolute_path) / "app/uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
API_KEY = os.getenv("GEMINI_API_KEY", "API_KEY")

_require_ragchatbot_access = require_project_access("ragchatbot")
_chat_rate_limit = rate_limit("chat", config.CHAT_RATE_LIMIT, config.RATE_LIMIT_WINDOW_SECONDS)
_ingest_rate_limit = rate_limit("ingest", config.INGEST_RATE_LIMIT, config.RATE_LIMIT_WINDOW_SECONDS)

# Bounds how long a blocking call (LLM request, vector search) is allowed to run.
# Note: chat_with_document already calls these synchronously with no await, so this
# doesn't make the endpoint non-blocking - it just turns "hangs forever" into "fails
# cleanly after REQUEST_TIMEOUT_SECONDS", which is the actual guardrail being added.
_pipeline_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)


async def _run_with_timeout(fn, *args, stage: str, timeout_seconds: int = config.REQUEST_TIMEOUT_SECONDS, **kwargs):
    '''Runs a blocking call on the pipeline thread pool and awaits it - not
    future.result(), which would block this coroutine's event loop thread for the
    entire duration and freeze every other in-flight request on this worker (logins,
    conversation list refreshes, other users' chats) until this one finishes.'''
    future = _pipeline_executor.submit(fn, *args, **kwargs)
    try:
        result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout_seconds)
        return result, None
    except asyncio.TimeoutError:
        reason = f"'{stage}' took longer than {timeout_seconds}s and was aborted."
        logger.warning("Guardrail blocked at timeout (%s): %s", stage, reason)
        return None, {"stage": "timeout", "passed": False, "reason": reason, "timed_out_stage": stage}


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    current_user: dict = Depends(_require_ragchatbot_access),
    _rate_limit_check: dict = Depends(_ingest_rate_limit),
):
    '''
    Ingest a document (PDF, XLSX, DOCX, or TXT) into the uploader's own knowledge base -
    retrieval only ever draws from documents this same user has ingested, never anyone
    else's. The file is saved in the uploads directory, chunked, PII-masked, and embedded
    for retrieval; a record
    of who uploaded it is kept for the Documents tab.
    '''
    try:
        content_bytes = await file.read()

        file_size_check = validate_file_size(len(content_bytes))
        if not file_size_check["passed"]:
            raise HTTPException(status_code=400, detail=file_size_check["reason"])

        file_type_check = validate_file_type(file.filename, content_bytes)
        if not file_type_check["passed"]:
            raise HTTPException(status_code=400, detail=file_type_check["reason"])

        # Generate unique filename
        extension = Path(file.filename).suffix
        filename = f"{uuid.uuid4()}{extension}"

        file_path = UPLOAD_DIR / filename
        file_path.write_bytes(content_bytes)

        logger.info("Saved uploaded file '%s' to '%s'", file.filename, file_path)

        from app.utils.ingest_files import ingest_files
        ingest = ingest_files([str(file_path)], user_id=current_user["_id"])

        if ingest["passed"]:
            logger.info("Ingestion succeeded for '%s'", file.filename)
        else:
            logger.error("Ingestion failed for '%s': %s", file.filename, ingest["error"])

        guardrails = {
            "file_type": file_type_check,
            "file_size": file_size_check,
            "pii_masking": ingest.get("pii_event"),
        }

        if not ingest["passed"]:
            return {
                "message": ingest["error"],
                "original_filename": file.filename,
                "content_type": file.content_type,
                "size": len(content_bytes),
                "guardrails": guardrails,
            }

        document = create_document_record(
            user_id=current_user["_id"],
            filename=file.filename,
            content_type=extension.lstrip(".").lower() or "unknown",
            size_bytes=len(content_bytes),
            extracted_text=ingest["extracted_text"],
            chunk_count=ingest["chunk_count"],
        )
        invalidate_bm25_cache(current_user["_id"])

        return {
            "message": ingest["message"],
            "document_id": document["_id"],
            "original_filename": file.filename,
            "content_type": file.content_type,
            "size": len(content_bytes),
            "chunk_count": ingest["chunk_count"],
            "guardrails": guardrails,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        file.file.close()

def _build_graph_response(state: QAResponse, compile: dict = None, extra_guardrail_events: list = None) -> dict:
    '''Full RAGState schema, guaranteed present regardless of which nodes ran.'''
    compile = compile or {}
    return {
        "question": compile.get("question", state.question),
        "retrieved_chunks": compile.get("retrieved_chunks", []),
        "reranked_chunks": compile.get("reranked_chunks", []),
        "context": compile.get("context", ""),
        "answer": compile.get("answer", ""),
        "logs": compile.get("logs", []),
        "blocked": compile.get("blocked", False),
        "block_reason": compile.get("block_reason"),
        "guardrail_events": (extra_guardrail_events or []) + compile.get("guardrail_events", []),
    }


def _persist_turn(
    conversation_id: str,
    user_id: str,
    question: str,
    response: dict,
    blocked: bool,
    start_time: float,
    cached: bool = False,
    question_embedding: list = None,
    cache_similarity: float = None,
    cache_source_message_id: str = None,
) -> None:
    '''Saves both sides of a turn and bumps the conversation's recency/title. question_embedding is
    only ever passed for a fresh, successful, non-cached answer - that's what makes a message a
    future cache candidate (see mongo.list_cache_candidates). Also stamps conversation_id and
    response_time_ms onto the response dict in place, so the caller (which may have auto-created
    this conversation) always tells the frontend which conversation the turn landed in and how long
    it took - measured from request receipt, so it covers every guardrail stage, not just the LLM call.'''
    response_time_ms = round((time.perf_counter() - start_time) * 1000, 1)
    response["conversation_id"] = conversation_id
    response["response_time_ms"] = response_time_ms
    add_message(conversation_id, user_id, "user", question)
    add_message(
        conversation_id, user_id, "assistant", response.get("answer", ""),
        question=question,
        logs=response.get("logs"),
        graph_response=response.get("graph_response"),
        blocked=blocked,
        cached=cached,
        question_embedding=question_embedding,
        cache_similarity=cache_similarity,
        cache_source_message_id=cache_source_message_id,
        response_time_ms=response_time_ms,
    )
    touch_conversation(conversation_id, first_question=question)


@router.post("/chat")
async def chat_with_document(
    state: QAResponse,
    current_user: dict = Depends(_require_ragchatbot_access),
    _rate_limit_check: dict = Depends(_chat_rate_limit),
):
    start = time.perf_counter()
    try:
        logger.info("Received chat request: question=%r", state.question)
        original_question = state.question
        # Overwrite unconditionally - a client-supplied user_id could otherwise be used
        # to read another user's ingested documents through retrieval's pre_filter.
        state.user_id = current_user["_id"]

        if state.conversation_id:
            conversation = get_conversation(state.conversation_id)
            if conversation is None or conversation["user_id"] != current_user["_id"]:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conversation_id = conversation["_id"]
        else:
            conversation_id = create_conversation(current_user["_id"])["_id"]

        input_check = validate_input(state.question)
        if not input_check["passed"]:
            logger.warning("Chat request blocked by input guardrail: %s", input_check["reason"])
            response = {
                "message": "Request blocked by input validation",
                "answer": f"I can't process this request: {input_check['reason']}",
                "logs": [f"[guardrail:input_validation] BLOCKED - {input_check['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=[input_check]),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response
        state.question = input_check["sanitized_question"]

        # Independent Mongo reads - awaited concurrently (asyncio.to_thread, not a
        # blocking ThreadPoolExecutor.result() call) so this coroutine doesn't freeze
        # the event loop - and hence every other in-flight request on this worker -
        # while waiting on either one.
        today = date.today().isoformat()
        has_documents, daily_usage = await asyncio.gather(
            asyncio.to_thread(user_has_documents, current_user["_id"]),
            asyncio.to_thread(get_daily_usage, current_user["_id"], today),
        )

        documents_event = validate_has_documents(has_documents)
        if not documents_event["passed"]:
            logger.warning("Chat request blocked by knowledge base guardrail: %s", documents_event["reason"])
            response = {
                "message": "Request blocked by knowledge base check",
                "answer": "You haven't ingested any documents yet. Upload one from the Document Ingestion tab before asking a question.",
                "logs": [f"[guardrail:documents_check] BLOCKED - {documents_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=[input_check, documents_event]),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response

        quota_event = validate_quota(daily_usage, current_user.get("role") == ROLE_ADMIN)
        if not quota_event["passed"]:
            logger.warning("Chat request blocked by quota guardrail: %s", quota_event["reason"])
            response = {
                "message": "Request blocked by quota",
                "answer": f"I'm sorry, this request can't be processed: {quota_event['reason']}",
                "logs": [f"[guardrail:quota_check] BLOCKED - {quota_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=[input_check, documents_event, quota_event]),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response

        classifier = IntentClassifier(api_key=API_KEY)
        result, timeout_event = await _run_with_timeout(classifier.classify_intent, state.question, stage="intent_classification")
        if timeout_event:
            response = {
                "message": "Request timed out",
                "answer": "I'm sorry, this request took too long to process. Please try again.",
                "logs": [f"[guardrail:timeout] BLOCKED - {timeout_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=[input_check, documents_event, quota_event, timeout_event]),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response
        increment_usage(current_user["_id"], today, result.get("token_count", 0))
        model_events = result.get("guardrail_events", [])
        guardrail_events = [input_check, documents_event, quota_event] + model_events

        blocked_event = next((e for e in model_events if not e["passed"]), None)
        if blocked_event:
            logger.warning("Chat request blocked by model guardrail (%s): %s", blocked_event["stage"], blocked_event["reason"])
            response = {
                "message": "Request blocked by model safety filter",
                "answer": f"I can't process this request: {blocked_event['reason']}",
                "logs": [f"[guardrail:{blocked_event['stage']}] BLOCKED - {blocked_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=guardrail_events),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response

        logger.info("Intent classified as '%s' with confidence %.2f", result["intent"], result["confidence"])
        intent_event = evaluate_intent_detection(result["intent"], result["confidence"])
        guardrail_events = guardrail_events + [intent_event]

        if not intent_event["passed"]:
            logger.warning("Chat request blocked by intent detection guardrail: %s", intent_event["reason"])
            response = {
                "message": "Request blocked by intent detection",
                "answer": "I'm sorry, I couldn't confidently tell what you're asking. Could you rephrase your question?",
                "logs": [f"[guardrail:intent_detection] BLOCKED - {intent_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=guardrail_events),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response

        if result["intent"] == "greetings":
            logger.info("Responded with greeting message")
            response = {
                "message": "Chat completed successfully",
                "answer": "Hello! How can I assist you today? Ask me a question about any of the documents you've uploaded.",
                "logs": ["Intent classified as 'greetings'. Responded with a greeting message.", "Intent classification confidence: {:.2f}".format(result["confidence"])],
                "graph_response": _build_graph_response(state, extra_guardrail_events=guardrail_events),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=False, start_time=start)
            return response

        cache_match, question_embedding = find_cache_match(current_user["_id"], state.question, embedding_model)
        cache_event = {
            "stage": "semantic_cache",
            "passed": True,
            "reason": (
                f"Reused an answer from a similar past question (similarity {cache_match['similarity']:.2f})."
                if cache_match else None
            ),
            "cache_hit": bool(cache_match),
            "similarity": cache_match["similarity"] if cache_match else None,
            "matched_question": cache_match["question"] if cache_match else None,
        }
        guardrail_events = guardrail_events + [cache_event]

        if cache_match:
            logger.info("Serving cached answer for user %s (similarity=%.3f)", current_user["_id"], cache_match["similarity"])
            response = {
                "message": "Chat completed successfully (cached)",
                "answer": cache_match["answer"],
                "images": [],
                "logs": [f"[guardrail:semantic_cache] HIT - reused answer from a similar past question (similarity {cache_match['similarity']:.2f})"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=guardrail_events),
            }
            _persist_turn(
                conversation_id, current_user["_id"], original_question, response, blocked=False, cached=True,
                cache_similarity=cache_match["similarity"],
                cache_source_message_id=cache_match["message_id"],
                start_time=start,
            )
            return response

        compile, timeout_event = await _run_with_timeout(compiled_graph.invoke, state, stage="answer_generation")
        if timeout_event:
            response = {
                "message": "Request timed out",
                "answer": "I'm sorry, this request took too long to process. Please try again.",
                "logs": [f"[guardrail:timeout] BLOCKED - {timeout_event['reason']}"],
                "graph_response": _build_graph_response(state, extra_guardrail_events=guardrail_events + [timeout_event]),
            }
            _persist_turn(conversation_id, current_user["_id"], original_question, response, blocked=True, start_time=start)
            return response
        increment_usage(current_user["_id"], today, compile.get("token_count", 0))
        image_paths = [x["image_path"] for x in compile["retrieved_chunks"] if x["content_type"] == "pdf_image"]
        logger.info("Chat completed successfully")

        graph_response = _build_graph_response(state, compile, extra_guardrail_events=guardrail_events)
        logger.debug("Full LangGraph state: %s", graph_response)

        blocked = compile.get("blocked", False)
        response = {
            "message": "Chat completed successfully",
            "answer": compile["answer"],
            "images": image_paths,
            "logs": [compile["logs"], "Intent classified as '{}' with confidence {:.2f}".format(result["intent"], result["confidence"])],
            "graph_response": graph_response,
        }
        _persist_turn(
            conversation_id, current_user["_id"], original_question, response, blocked=blocked, cached=False,
            question_embedding=question_embedding if not blocked else None,
            start_time=start,
        )
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error while handling chat request: %s", e)
        raise HTTPException(status_code=500, detail=str(e))