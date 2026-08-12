import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core import guardrail_config
from app.core.guardrails import cosine_similarity
from app.core.logger import get_logger
from app.utils.mongo import list_cache_candidates

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Named-entity guard
#
# Cosine similarity alone can't tell "Give me the summary of Denice Harris resume"
# apart from "Give me the summary of Ghiridhar's resume" - two structurally
# identical questions differing only by which person/document they name embed
# close enough (~0.94) to clear the default 0.93 threshold, serving the wrong
# person's cached answer. Fixed with a cheap regex heuristic instead of a full
# NER model (fast enough to run on every cache lookup): pull out maximal runs of
# capitalized words - "Denice Harris", "Ghiridhar's" - as proxy named entities,
# and only allow a cache hit when the new question and the candidate's stored
# question reference the exact same set of them (including both referencing
# none, which is the common case for topic questions with no named entity at
# all - "what is the warranty period").
# ---------------------------------------------------------------------------

_CAP_RUN_RE = re.compile(r"\b[A-Z][a-zA-Z']*(?:\s+[A-Z][a-zA-Z']*)*\b")


def _salient_entities(text: str) -> Set[str]:
    entities: Set[str] = set()
    for match in _CAP_RUN_RE.finditer(text or ""):
        words = match.group().split()
        if match.start() == 0:
            # The question's very first word is almost always just normal
            # sentence-initial capitalization ("What", "Give", "Summarize"), not a
            # named entity - drop only that leading word. If a real name immediately
            # follows with no lowercase word between them ("Summarize Denice Harris
            # resume"), it's part of this same regex match, so it must be peeled off
            # here rather than skipping the whole run.
            words = words[1:]
        if words:
            entities.add(" ".join(words).lower())
    return entities


def find_cache_match(
    user_id: str, question: str, embedding_model: Any
) -> Tuple[Optional[Dict[str, Any]], Optional[List[float]]]:
    '''Looks for a highly-similar question this same user already got a real (non-blocked,
    non-cached) answer for. Deliberately scoped to one user - never reuses another user's
    answers. Brute-force cosine similarity over a recent-message window
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

    cfg = guardrail_config.get_config()
    candidates = list_cache_candidates(user_id, cfg["semantic_cache_max_candidates"])
    if not candidates:
        return None, question_embedding

    question_entities = _salient_entities(question)

    best = None
    best_score = 0.0
    for candidate in candidates:
        if question_entities != _salient_entities(candidate.get("question") or ""):
            continue
        score = cosine_similarity(question_embedding, candidate["question_embedding"])
        if score > best_score:
            best_score = score
            best = candidate

    if best is None or best_score < cfg["semantic_cache_similarity_threshold"]:
        return None, question_embedding

    logger.info(
        "Semantic cache hit for user %s: similarity=%.3f matched_question=%r",
        user_id, best_score, best.get("question"),
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
