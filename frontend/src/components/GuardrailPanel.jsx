const PII_LABELS = {
  EMAIL_ADDRESS: "Email address",
  PHONE_NUMBER: "Phone number",
  CREDIT_CARD: "Credit card",
  US_SSN: "SSN",
  US_BANK_NUMBER: "Bank account number",
  US_DRIVER_LICENSE: "Driver's license",
  US_PASSPORT: "Passport number",
  IBAN_CODE: "IBAN",
  IP_ADDRESS: "IP address",
  CRYPTO: "Crypto wallet address",
  PERSON: "Person name",
  LOCATION: "Location",
  NRP: "Nationality / religious / political group",
  MEDICAL_LICENSE: "Medical license",
};

function piiLabel(entityType) {
  return PII_LABELS[entityType] || entityType;
}

// The full, fixed guardrail pipeline, in the order it actually runs. Every entry is
// always shown, regardless of whether that check ran for a given message - `resolve`
// pulls its real result out of the event data returned for this turn, or the row
// falls back to "not run" (e.g. everything after input_validation when the request
// got blocked at the very first stage).
const CHECKLIST = [
  {
    id: "input.length",
    label: "Input length",
    group: "Input",
    resolve: (events) => subCheck(events, "input_validation", "length"),
  },
  {
    id: "input.prompt_injection_regex",
    label: "Prompt injection (pattern match)",
    group: "Input",
    resolve: (events) => subCheck(events, "input_validation", "prompt_injection_regex"),
  },
  {
    id: "input.blocked_keywords",
    label: "Blocked keywords",
    group: "Input",
    resolve: (events) => subCheck(events, "input_validation", "blocked_keywords"),
  },
  {
    id: "input.pii_masking",
    label: "PII detection & masking",
    group: "Input",
    resolve: (events) => subCheck(events, "input_validation", "pii_masking"),
  },
  {
    id: "quota_check",
    label: "Daily token quota",
    group: "Quota",
    resolve: (events) => stageCheck(events, "quota_check"),
  },
  {
    id: "model_input_validation",
    label: "Model safety classifier",
    group: "Model (input)",
    resolve: (events) => stageCheck(events, "model_input_validation"),
  },
  {
    id: "intent_output_schema",
    label: "Response schema valid",
    group: "Model (input)",
    resolve: (events) => stageCheck(events, "intent_output_schema"),
  },
  {
    id: "model_prompt_injection_check",
    label: "Prompt injection (model judgment)",
    group: "Model (input)",
    resolve: (events) => stageCheck(events, "model_prompt_injection_check"),
  },
  {
    id: "intent_detection",
    label: "Intent detected",
    group: "Intent",
    resolve: (events) => stageCheck(events, "intent_detection"),
  },
  {
    id: "collection_authorization",
    label: "Collection authorized",
    group: "Routing",
    resolve: (events) => stageCheck(events, "collection_authorization"),
  },
  {
    id: "semantic_cache",
    label: "Similar question cache",
    group: "Cache",
    resolve: (events) => stageCheck(events, "semantic_cache"),
  },
  {
    id: "retrieval_validation",
    label: "Retrieval relevance",
    group: "Retrieval",
    resolve: (events) => stageCheck(events, "retrieval_validation"),
  },
  {
    id: "context_budget",
    label: "Context budget",
    group: "Retrieval",
    resolve: (events) => stageCheck(events, "context_budget"),
  },
  {
    id: "model_output_validation",
    label: "Model safety classifier",
    group: "Model (output)",
    resolve: (events) => stageCheck(events, "model_output_validation"),
  },
  {
    id: "model_output_schema",
    label: "Response schema valid",
    group: "Model (output)",
    resolve: (events) => stageCheck(events, "model_output_schema"),
  },
  {
    id: "groundedness_check",
    label: "Grounded in retrieved context",
    group: "Answer quality",
    resolve: (events) => stageCheck(events, "groundedness_check"),
  },
  {
    id: "output.not_empty",
    label: "Answer not empty",
    group: "Output",
    resolve: (events) => subCheck(events, "output_validation", "not_empty"),
  },
  {
    id: "output.blocked_keywords",
    label: "Blocked keywords",
    group: "Output",
    resolve: (events) => subCheck(events, "output_validation", "blocked_keywords"),
  },
  {
    id: "output.pii_masking",
    label: "PII detection & masking",
    group: "Output",
    resolve: (events) => subCheck(events, "output_validation", "pii_masking"),
  },
  {
    id: "output.url_allowlist",
    label: "Link allowlist",
    group: "Output",
    resolve: (events) => subCheck(events, "output_validation", "url_allowlist"),
  },
  {
    id: "output.length_limit",
    label: "Answer length limit",
    group: "Output",
    resolve: (events) => subCheck(events, "output_validation", "length_limit"),
  },
];

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

const STATUS_META = {
  pass: { icon: "✅", label: "Passed" },
  fail: { icon: "🚫", label: "Blocked" },
  skipped: { icon: "⏭️", label: "Skipped" },
  not_run: { icon: "—", label: "Not run" },
};

function GuardrailRow({ item, events }) {
  const result = item.resolve(events);
  const meta = STATUS_META[result.status];
  const piiDetected = result.piiDetected || [];
  const flaggedCategories = result.flaggedCategories || [];

  return (
    <div className={`guardrail-row guardrail-row-${result.status}`}>
      <div className="guardrail-row-head">
        <span className="guardrail-event-icon">{meta.icon}</span>
        <span className="guardrail-event-stage">{item.label}</span>
        <span className={`guardrail-status-tag guardrail-status-${result.status}`}>{meta.label}</span>
      </div>

      {result.reason && <p className="guardrail-event-reason">{result.reason}</p>}

      {piiDetected.length > 0 && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">Masked:</span>
          {piiDetected.map((p) => (
            <span key={p.entity_type} className="guardrail-badge guardrail-badge-pii">
              {piiLabel(p.entity_type)}
              {p.count > 1 ? ` ×${p.count}` : ""}
            </span>
          ))}
        </div>
      )}

      {flaggedCategories.length > 0 && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">Flagged:</span>
          {flaggedCategories.map((c) => (
            <span key={c} className="guardrail-badge guardrail-badge-warn">
              {c.replace("HARM_CATEGORY_", "").replaceAll("_", " ").toLowerCase()}
            </span>
          ))}
        </div>
      )}

      {result.intent !== undefined && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">{result.status === "pass" ? "Detected:" : "Best guess:"}</span>
          <span className={`guardrail-badge ${result.status === "pass" ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
            {result.intent}
            {typeof result.confidence === "number" ? ` (${Math.round(result.confidence * 100)}%)` : ""}
          </span>
        </div>
      )}

      {typeof result.tokensUsedToday === "number" && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">Usage:</span>
          <span className="guardrail-badge">
            {result.tokensUsedToday.toLocaleString()} / {result.dailyQuota?.toLocaleString()} tokens today
          </span>
        </div>
      )}

      {typeof result.groundednessScore === "number" && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">Similarity:</span>
          <span className={`guardrail-badge ${result.status === "pass" ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
            {result.groundednessScore.toFixed(2)}
          </span>
        </div>
      )}

      {typeof result.cacheHit === "boolean" && (
        <div className="guardrail-pii">
          <span className="guardrail-pii-label">{result.cacheHit ? "Reused:" : "Cache:"}</span>
          <span className={`guardrail-badge ${result.cacheHit ? "guardrail-badge-pii" : ""}`}>
            {result.cacheHit
              ? `"${result.matchedQuestion}" (similarity ${result.cacheSimilarity?.toFixed(2)})`
              : "No similar past question found"}
          </span>
        </div>
      )}
    </div>
  );
}

export default function GuardrailPanel({ logs, graphResponse }) {
  const events = graphResponse?.guardrail_events || [];

  const groups = [];
  for (const item of CHECKLIST) {
    let group = groups.find((g) => g.name === item.group);
    if (!group) {
      group = { name: item.group, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }

  return (
    <div className="chat-logs">
      <div className="guardrail-list">
        {groups.map((group) => (
          <div key={group.name} className="guardrail-group">
            <h4 className="guardrail-group-title">{group.name}</h4>
            {group.items.map((item) => (
              <GuardrailRow key={item.id} item={item} events={events} />
            ))}
          </div>
        ))}
      </div>

      {logs?.length > 0 && (
        <details className="chat-raw-logs">
          <summary>Raw execution logs</summary>
          {logs.map((log, j) => (
            <div key={j} className="chat-log-line">
              {typeof log === "string" ? log : JSON.stringify(log)}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
