from pathlib import Path
from typing import Any, Dict, List

from app.core import config
from app.core.guardrails import redact_pii, summarize_masked_pii
from app.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# File type guardrail
#
# Magic-byte sniff instead of trusting the filename extension / browser-supplied
# content-type - a renamed executable or malformed archive would otherwise sail
# straight through. Deliberately not using python-magic (needs a libmagic
# system binary, painful on Windows) since we only need to recognize the two
# formats this app actually accepts.
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # .xlsx is a zip archive under the hood

_EXPECTED_MAGIC = {
    ".pdf": (_PDF_MAGIC, "PDF"),
    ".xlsx": (_ZIP_MAGIC, "XLSX"),
}


def validate_file_type(filename: str, content_bytes: bytes, check: str = "file_type") -> Dict[str, Any]:
    ext = Path(filename or "").suffix.lower()
    expected = _EXPECTED_MAGIC.get(ext)

    if expected is None:
        reason = f"Unsupported file extension '{ext or '(none)'}'. Must be one of: {', '.join(_EXPECTED_MAGIC)}."
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
# ---------------------------------------------------------------------------

def scan_ingested_pii(chunks: List[Any], check: str = "pii_masking") -> Dict[str, Any]:
    aggregated: Dict[str, int] = {}

    for chunk in chunks:
        original = chunk.page_content
        redacted = redact_pii(original)
        if redacted == original:
            continue
        chunk.page_content = redacted
        for entry in summarize_masked_pii(redacted):
            aggregated[entry["entity_type"]] = aggregated.get(entry["entity_type"], 0) + entry["count"]

    pii_detected = [{"entity_type": k, "count": v} for k, v in sorted(aggregated.items())]
    if pii_detected:
        logger.warning("Redacted PII from ingested document: %s", pii_detected)

    return {"check": check, "passed": True, "reason": None, "pii_detected": pii_detected}
