from pathlib import Path
from typing import Any, Dict, List

from app.core import config, guardrail_config
from app.core.guardrails import redact_pii, summarize_masked_pii
from app.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# File type guardrail
#
# Magic-byte sniff instead of trusting the filename extension / browser-supplied
# content-type - a renamed executable or malformed archive would otherwise sail
# straight through. Deliberately not using python-magic (needs a libmagic
# system binary, painful on Windows) - the small fixed set of formats this app
# accepts is cheap to recognize by a plain byte-prefix check instead.
#
# .docx/.xlsx are both zip archives under the hood (OOXML) and share the same
# magic bytes - the extension picks which loader runs in ingest_files.py, the
# magic check here only confirms "this really is a zip", not which kind.
# .txt has no fixed signature at all, so it's checked differently: it must
# decode as UTF-8 text rather than match a byte prefix. Legacy binary .doc
# (pre-2007 Word) is deliberately NOT supported - it needs different, heavier
# tooling than anything else here.
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

_EXPECTED_MAGIC = {
    ".pdf": (_PDF_MAGIC, "PDF"),
    ".xlsx": (_ZIP_MAGIC, "XLSX"),
    ".docx": (_ZIP_MAGIC, "DOCX"),
}
_TEXT_EXTENSIONS = {".txt"}
SUPPORTED_EXTENSIONS = sorted(set(_EXPECTED_MAGIC) | _TEXT_EXTENSIONS)


def validate_file_type(filename: str, content_bytes: bytes, check: str = "file_type") -> Dict[str, Any]:
    ext = Path(filename or "").suffix.lower()

    if ext in _TEXT_EXTENSIONS:
        try:
            content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            reason = "File content is not valid UTF-8 text."
            logger.warning("Guardrail blocked at ingest.%s: %s (filename=%r)", check, reason, filename)
            return {"check": check, "passed": False, "reason": reason}
        return {"check": check, "passed": True, "reason": None}

    expected = _EXPECTED_MAGIC.get(ext)
    if expected is None:
        reason = f"Unsupported file extension '{ext or '(none)'}'. Must be one of: {', '.join(SUPPORTED_EXTENSIONS)}."
        logger.warning("Guardrail blocked at ingest.%s: %s", check, reason)
        return {"check": check, "passed": False, "reason": reason}

    magic, label = expected
    if not content_bytes.startswith(magic):
        reason = f"File content does not match its extension - expected a valid {label} file."
        logger.warning("Guardrail blocked at ingest.%s: %s (filename=%r)", check, reason, filename)
        return {"check": check, "passed": False, "reason": reason}

    return {"check": check, "passed": True, "reason": None}


# ---------------------------------------------------------------------------
# File size guardrail
# ---------------------------------------------------------------------------

def validate_file_size(size_bytes: int, check: str = "file_size") -> Dict[str, Any]:
    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size_bytes > max_bytes:
        reason = f"File is {size_bytes / (1024 * 1024):.1f}MB, exceeds the {config.MAX_UPLOAD_SIZE_MB}MB limit."
        logger.warning("Guardrail blocked at ingest.%s: %s", check, reason)
        return {"check": check, "passed": False, "reason": reason}

    return {"check": check, "passed": True, "reason": None}


# ---------------------------------------------------------------------------
# PII masking on ingested content
#
# The same redact_pii()/summarize_masked_pii() already used on chat questions
# and answers, applied to every chunk *before* it's embedded and stored - PII
# baked into an uploaded PDF/XLSX shouldn't sit unmasked in the vector store.
#
# entities/score_threshold are the uploader's own choice from the Document
# Ingestion screen (any user, not just admins - see POST /ingest's
# `pii_entities` form field), falling back to guardrail_config's
# ingest_pii_entities/ingest_pii_score_threshold defaults when the uploader
# didn't pick anything. This is a separate policy from chat input/output PII
# detection, which admins tune on the Guardrails page instead.
# ---------------------------------------------------------------------------

def scan_ingested_pii(
    chunks: List[Any],
    entities: List[str] = None,
    score_threshold: float = None,
    check: str = "pii_masking",
) -> Dict[str, Any]:
    cfg = guardrail_config.get_config()
    if entities is None:
        entities = cfg["ingest_pii_entities"]
    if score_threshold is None:
        score_threshold = cfg["ingest_pii_score_threshold"]

    aggregated: Dict[str, int] = {}

    for chunk in chunks:
        original = chunk.page_content
        redacted = redact_pii(original, entities, score_threshold)
        if redacted == original:
            continue
        chunk.page_content = redacted
        for entry in summarize_masked_pii(redacted):
            aggregated[entry["entity_type"]] = aggregated.get(entry["entity_type"], 0) + entry["count"]

    pii_detected = [{"entity_type": k, "count": v} for k, v in sorted(aggregated.items())]
    if pii_detected:
        logger.warning("Redacted PII from ingested document: %s", pii_detected)

    return {"check": check, "passed": True, "reason": None, "pii_detected": pii_detected}
