// Single source of truth for the guardrail pipeline: the live per-turn panel
// (GuardrailPanel) and the static catalog (Traces project's "Guardrails" tab)
// both read this list, so a new check only needs to be described once.
//
// `resolve` pulls a stage's real result out of a turn's guardrail_events; the
// catalog view ignores it and only reads label/group/description.
//
// Each item also carries `category` (Input / Retrieval / Output - which stage
// of the pipeline it runs at) and `type` (Deterministic - fixed rules/thresholds
// whose outcome you could predict just by reading the rule; Model-based - the
// verdict comes from a trained model's inference: Gemini's safety/judgment
// calls, or a similarity/confidence score produced by an embedding or NER
// model). These only drive the catalog's Input/Retrieval/Output grouping -
// `group` is unchanged and still drives GuardrailPanel's live per-turn view.

function firstEventForStage(events, stage) {
  return (events || []).find((e) => e.stage === stage);
}

function stageCheck(events, stage) {
  const event = firstEventForStage(events, stage);
  if (!event) return { status: "not_run" };
  return {
    status: event.passed ? "pass" : "fail",
    reason: event.reason,
    flaggedCategories: event.flagged_categories,
    intent: event.intent,
    confidence: event.confidence,
    tokensUsedToday: event.tokens_used_today,
    dailyQuota: event.daily_quota,
    groundednessScore: event.score,
    cacheHit: event.cache_hit,
    cacheSimilarity: event.similarity,
    matchedQuestion: event.matched_question,
    routedSources: event.routed_sources,
    availableSources: event.available_sources,
    routingConfidence: event.routing_confidence,
    routingMethod: event.routing_method,
    nearMissChunks: event.near_miss_chunks,
    flaggedChunks: event.flagged_chunks,
    excludedCount: event.excluded_count,
    checkedCount: event.checked_count,
    action: event.action,
  };
}

function subCheck(events, stage, checkId) {
  const event = firstEventForStage(events, stage);
  const entry = event?.checks?.find((c) => c.check === checkId);
  if (!entry) return { status: "not_run" };
  if (entry.passed === null) return { status: "skipped", reason: entry.reason };
  return {
    status: entry.passed ? "pass" : "fail",
    reason: entry.reason,
    piiDetected: entry.pii_detected,
  };
}

export const GUARDRAIL_CHECKLIST = [
  {
    id: "input.length",
    label: "Input length",
    group: "Input",
    category: "Input",
    type: "Deterministic",
    description: "Rejects questions under 2 characters or over 2,000.",
    resolve: (events) => subCheck(events, "input_validation", "length"),
  },
  {
    id: "input.prompt_injection_regex",
    label: "Prompt injection (pattern match)",
    group: "Input",
    category: "Input",
    type: "Deterministic",
    description:
      "Blocks known jailbreak phrasings (\"ignore previous instructions\", \"reveal your system prompt\", etc.) via regex.",
    resolve: (events) => subCheck(events, "input_validation", "prompt_injection_regex"),
  },
  {
    id: "input.blocked_keywords",
    label: "Blocked keywords",
    group: "Input",
    category: "Input",
    type: "Deterministic",
    description: "Rejects questions containing a small denylist of clearly disallowed phrases.",
    resolve: (events) => subCheck(events, "input_validation", "blocked_keywords"),
  },
  {
    id: "input.pii_masking",
    label: "PII detection & masking",
    group: "Input",
    category: "Input",
    type: "Model-based",
    description:
      "Detects free-text PII (names, emails, phone numbers, SSNs, and more) with a local Presidio/spaCy model and replaces each span with a reversibly-encrypted token before the question is used further.",
    resolve: (events) => subCheck(events, "input_validation", "pii_masking"),
  },
  {
    id: "documents_check",
    label: "Knowledge base not empty",
    group: "Knowledge base",
    category: "Input",
    type: "Deterministic",
    description:
      "Blocks the entire turn, including greetings, if the user hasn't ingested any documents of their own yet - retrieval only ever searches a user's own uploads, so there's nothing to answer from otherwise. No admin exemption.",
    resolve: (events) => stageCheck(events, "documents_check"),
  },
  {
    id: "quota_check",
    label: "Daily token quota",
    group: "Quota",
    category: "Input",
    type: "Deterministic",
    description: "Blocks the request once the user's token usage for today reaches the daily quota. Admins are exempt.",
    resolve: (events) => stageCheck(events, "quota_check"),
  },
  {
    id: "model_input_validation",
    label: "Model safety classifier",
    group: "Model (input)",
    category: "Input",
    type: "Model-based",
    description:
      "Rides on the intent-classification call: inspects Gemini's built-in harm-category ratings (harassment, hate speech, sexual content, dangerous content) for the question.",
    resolve: (events) => stageCheck(events, "model_input_validation"),
  },
  {
    id: "intent_output_schema",
    label: "Response schema valid",
    group: "Model (input)",
    category: "Input",
    type: "Deterministic",
    description: "Confirms the model's JSON response for intent classification actually parses and has the expected fields.",
    resolve: (events) => stageCheck(events, "intent_output_schema"),
  },
  {
    id: "model_prompt_injection_check",
    label: "Prompt injection (model judgment)",
    group: "Model (input)",
    category: "Input",
    type: "Model-based",
    description:
      "Asks the LLM itself to judge whether the question is a jailbreak/injection attempt semantically, catching paraphrased attacks the regex check misses.",
    resolve: (events) => stageCheck(events, "model_prompt_injection_check"),
  },
  {
    id: "self_harm_check",
    label: "Self-harm / crisis content",
    group: "Model (input)",
    category: "Input",
    type: "Model-based",
    description:
      "Asks the LLM itself to judge whether the question requests self-harm or suicide methods, ideation, or encouragement - including academically or clinically framed requests - since Gemini's harm categories have no dedicated self-harm bucket and the keyword denylist is easily bypassed by rewording.",
    resolve: (events) => stageCheck(events, "self_harm_check"),
  },
  {
    id: "intent_detection",
    label: "Intent detected",
    group: "Intent",
    category: "Input",
    type: "Model-based",
    description:
      "Requires at least 80% model confidence that the question is a genuine question (as opposed to a greeting) before retrieval continues.",
    resolve: (events) => stageCheck(events, "intent_detection"),
  },
  {
    id: "topic_restriction",
    label: "Topic restriction",
    group: "Model (input)",
    category: "Input",
    type: "Model-based",
    description:
      "When an admin configures an approved-topics list, rides on the intent-classification call to judge whether the question's subject matter falls within it. Shows as not run unless topics are configured.",
    resolve: (events) => stageCheck(events, "topic_restriction"),
  },
  {
    id: "escalation_check",
    label: "Multi-turn escalation",
    group: "Model (input)",
    category: "Input",
    type: "Model-based",
    description:
      "Rides on the same intent-classification call, judging the current message against the recent conversation history for a jailbreak spread innocuously across turns (e.g. asking what the rules are, then which could be relaxed, then asking the assistant to act as if they were) - something no single-message check can catch. Shows as not run on a conversation's first turn, since there's no history yet to escalate from.",
    resolve: (events) => stageCheck(events, "escalation_check"),
  },
  {
    id: "document_routing",
    label: "Document routing",
    group: "Retrieval",
    category: "Retrieval",
    type: "Deterministic",
    description:
      "When a user has more than one uploaded document, scores each one's relevance to the question (word-overlap against its extracted text) and narrows retrieval to the confident match(es) - a question can route to more than one document. Never blocks: below the confidence floor, disabled, or for a single-document user, it searches the whole corpus exactly as before this check existed.",
    resolve: (events) => stageCheck(events, "document_routing"),
  },
  {
    id: "semantic_cache",
    label: "Similar question cache",
    group: "Cache",
    category: "Retrieval",
    type: "Model-based",
    description:
      "Checks whether a highly similar past question (cosine similarity ≥ 0.93) was already answered for this user; if so, returns that answer directly and skips retrieval and generation.",
    resolve: (events) => stageCheck(events, "semantic_cache"),
  },
  {
    id: "retrieval_validation",
    label: "Retrieval relevance",
    group: "Retrieval",
    category: "Retrieval",
    type: "Model-based",
    description: "Filters retrieved chunks below the admin-configured minimum relevance score and keeps at most the top-N chunks (both tunable below).",
    resolve: (events) => stageCheck(events, "retrieval_validation"),
  },
  {
    id: "context_budget",
    label: "Context budget",
    group: "Retrieval",
    category: "Retrieval",
    type: "Deterministic",
    description: "Trims retrieved chunks to stay within a ~128,000 character context budget, dropping the lowest-ranked chunks first.",
    resolve: (events) => stageCheck(events, "context_budget"),
  },
  {
    id: "model_output_validation",
    label: "Model safety classifier",
    group: "Model (output)",
    category: "Output",
    type: "Model-based",
    description: "The same Gemini harm-category check as above, run again on the answer-generation call.",
    resolve: (events) => stageCheck(events, "model_output_validation"),
  },
  {
    id: "model_output_schema",
    label: "Response schema valid",
    group: "Model (output)",
    category: "Output",
    type: "Deterministic",
    description: "Confirms the model's JSON response for answer generation parses and has the expected fields.",
    resolve: (events) => stageCheck(events, "model_output_schema"),
  },
  {
    id: "groundedness_check",
    label: "Grounded in retrieved context",
    group: "Answer quality",
    category: "Output",
    type: "Model-based",
    description:
      "Compares the answer's embedding against the retrieved context's embedding; blocks if cosine similarity falls below minimum groundedness score, meaning the answer isn't well supported by the retrieved documents.",
    resolve: (events) => stageCheck(events, "groundedness_check"),
  },
  {
    id: "bias_detection",
    label: "Bias detection",
    group: "Answer quality",
    category: "Output",
    type: "Model-based",
    description:
      "Asks the model to self-report whether its own answer shows unfair characterization by a protected attribute, riding on the answer-generation call. Admin-toggleable.",
    resolve: (events) => stageCheck(events, "bias_detection"),
  },
  {
    id: "context_injection_filter",
    label: "Indirect context injection",
    group: "Retrieval",
    category: "Retrieval",
    type: "Model-based",
    description:
      "A dedicated, small/fast classifier call scores every retrieved chunk for text addressed to the AI - an attempt to override its instructions embedded in an uploaded file - before the answering call ever sees them. Flagged chunks are excluded from context outright, not merely instructed against. Doesn't block the turn: the answer is generated from the remaining chunks, with a deterministic notice appended whenever anything was excluded. Admin-toggleable.",
    resolve: (events) => stageCheck(events, "context_injection_filter"),
  },
  {
    id: "output.not_empty",
    label: "Answer not empty",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description: "Blocks an empty generated answer from ever reaching the user.",
    resolve: (events) => subCheck(events, "output_validation", "not_empty"),
  },
  {
    id: "output.blocked_keywords",
    label: "Blocked keywords",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description: "Scans the generated answer against the same denylist used on input.",
    resolve: (events) => subCheck(events, "output_validation", "blocked_keywords"),
  },
  {
    id: "output.compliance_validation",
    label: "Compliance validation",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description:
      "Scans the generated answer for definitive regulated-claim phrases (e.g. guaranteed returns, guaranteed cures) that shouldn't be stated without review.",
    resolve: (events) => subCheck(events, "output_validation", "compliance_validation"),
  },
  {
    id: "output.pii_masking",
    label: "PII detection & masking",
    group: "Output",
    category: "Output",
    type: "Model-based",
    description: "Runs the same Presidio/spaCy PII detector on the generated answer before it's returned.",
    resolve: (events) => subCheck(events, "output_validation", "pii_masking"),
  },
  {
    id: "output.url_allowlist",
    label: "Link allowlist",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description: "Strips any link whose domain isn't explicitly allowlisted — there's no legitimate reason this bot should emit external links.",
    resolve: (events) => subCheck(events, "output_validation", "url_allowlist"),
  },
  {
    id: "output.length_limit",
    label: "Answer length limit",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description: "Truncates any answer over 6,000 characters.",
    resolve: (events) => subCheck(events, "output_validation", "length_limit"),
  },
  {
    id: "output.tone_check",
    label: "Tone calibration",
    group: "Output",
    category: "Output",
    type: "Deterministic",
    description:
      "Flags (without blocking) informal phrasing — shouting punctuation or slang — that drifts from a professional tone. Admin-toggleable.",
    resolve: (events) => subCheck(events, "output_validation", "tone_check"),
  },
];

// The database agent reuses validate_input/validate_quota/validate_output
// verbatim (see app/api/v1/database.py's POST /chat), so their events are the
// exact same shape as the document pipeline's - only the retrieval-specific and
// document-only checks (knowledge base, model safety, intent, cache, retrieval,
// groundedness) don't apply, since there's no retrieval step to check.
const DATABASE_CHECKLIST_IDS = [
  "input.length", "input.prompt_injection_regex", "input.blocked_keywords", "input.pii_masking",
  "quota_check",
  "output.not_empty", "output.blocked_keywords", "output.compliance_validation", "output.pii_masking",
  "output.url_allowlist", "output.length_limit", "output.tone_check",
];

export const DATABASE_GUARDRAIL_CHECKLIST = GUARDRAIL_CHECKLIST.filter((item) => DATABASE_CHECKLIST_IDS.includes(item.id));

export function groupChecklist(checklist = GUARDRAIL_CHECKLIST) {
  const groups = [];
  for (const item of checklist) {
    let group = groups.find((g) => g.name === item.group);
    if (!group) {
      group = { name: item.group, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

const CATEGORY_ORDER = ["Input", "Retrieval", "Output"];
const TYPE_ORDER = ["Deterministic", "Model-based"];

// Catalog view for the Guardrails tab: Input -> Retrieval -> Output, each split
// into its Deterministic and Model-based checks.
export function groupChecklistByCategory(checklist = GUARDRAIL_CHECKLIST) {
  return CATEGORY_ORDER.map((category) => ({
    name: category,
    subgroups: TYPE_ORDER.map((type) => ({
      name: type,
      items: checklist.filter((item) => item.category === category && item.type === type),
    })).filter((sub) => sub.items.length > 0),
  })).filter((cat) => cat.subgroups.length > 0);
}

// "Which guardrail blocked this turn, by name" - for the chat UI's "Blocked - {name}"
// badge. input_validation/output_validation aren't 1:1 with a single checklist item
// (they fan out into input.*/output.* sub-checks via event.checks[]/event.category -
// see stageCheck/subCheck above), so those two stages need the extra step every other
// stage doesn't. Falls back to a capitalized stage name rather than nothing, so an
// unmapped/future stage still shows *something* instead of silently hiding the badge.
function humanizeStage(stage) {
  return (stage || "Guardrail").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Stages that can report passed: false (something genuinely found/flagged) without
// blocking the turn - context_injection_filter excludes the flagged chunk(s) and
// answers from what's left, rather than discarding a good answer (see
// app/core/guardrails.py's evaluate_injection_filter docstring), so it must never
// trigger this badge - filter_injected_chunks_node never sets state["blocked"] either.
const NON_BLOCKING_FAILURE_STAGES = new Set(["context_injection_filter"]);

export function resolveBlockedGuardrailLabel(events) {
  const failed = (events || []).find((e) => e.passed === false && !NON_BLOCKING_FAILURE_STAGES.has(e.stage));
  if (!failed) return null;

  let itemId = failed.stage;
  if (failed.stage === "input_validation") {
    itemId = failed.category ? `input.${failed.category}` : null;
  } else if (failed.stage === "output_validation") {
    const failedCheck = failed.checks?.find((c) => c.passed === false);
    itemId = failedCheck ? `output.${failedCheck.check}` : null;
  }

  const item = itemId && GUARDRAIL_CHECKLIST.find((i) => i.id === itemId);
  return item?.label || humanizeStage(failed.stage);
}
