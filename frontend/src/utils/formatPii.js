// Masked PII is stored/returned as a reversibly-encrypted token, e.g.
// "[[PII:PERSON:gAAAAABq...==]]" (see app/core/guardrails.py's _ENCODED_PII_RE).
// Nothing decrypts these client-side, so the raw blob is just noise to a reader -
// this collapses it down to the entity type alone, e.g. "PII:PERSON".
const PII_TOKEN_RE = /\[\[PII:([A-Z_]+):[A-Za-z0-9_\-=]+\]\]/g;

export function formatPiiTokens(text) {
  if (!text) return text;
  return text.replace(PII_TOKEN_RE, "PII:$1");
}
