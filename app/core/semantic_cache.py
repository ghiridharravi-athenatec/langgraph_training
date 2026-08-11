from typing import Any, Dict, List, Optional, Tuple

from app.core import config
from app.core.guardrails import cosine_similarity
from app.core.logger import get_logger
from app.utils.mongo import list_cache_candidates

logger = get_logger(__name__)


def find_cache_match(
    user_id: str, collection_name: str, question: str, embedding_model: Any
) -> Tuple[Optional[Dict[str, Any]], Optional[List[float]]]:
    '''Looks for a highly-similar question this same user already got a real (non-blocked,
    non-cached) answer for in this document collection. Deliberately scoped to one user - never
    reuses another user's answers. Brute-force cosine similarity over a recent-message window
    (SEMANTIC_CACHE_MAX_CANDIDATES) rather than a dedicated vector index, matching this codebase's
    existing "no new Atlas Search index unless retrieval quality needs it" stance.

    Returns (match, question_embedding). match is
    {message_id, question, answer, similarity, logs, graph_response} on a hit, else None.
    question_embedding is returned even on a miss/error=None-embedding-failure, so a fresh answer
    can be stored as a future cache candidate without re-embedding the same question twice.
    '''
    try:
        question_embedding = embedding_model.embed_query(question)
    except Exception:
        logger.exception("Semantic cache lookup failed to embed the question - skipping cache check")
        return None, None

    candidates = list_cache_candidates(user_id, collection_name, config.SEMANTIC_CACHE_MAX_CANDIDATES)
    if not candidates:
        return None, question_embedding

    best = None
    best_score = 0.0
    for candidate in candidates:
        score = cosine_similarity(question_embedding, candidate["question_embedding"])
        if score > best_score:
            best_score = score
            best = candidate

    if best is None or best_score < config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD:
        return None, question_embedding

    logger.info(
        "Semantic cache hit for user %s in '%s': similarity=%.3f matched_question=%r",
        user_id, collection_name, best_score, best.get("question"),
    )
    match = {
        "message_id": best["_id"],
        "question": best.get("question"),
        "answer": best["content"],
        "similarity": best_score,
        "logs": best.get("logs"),
        "graph_response": best.get("graph_response"),
    }
    return match, question_embedding
