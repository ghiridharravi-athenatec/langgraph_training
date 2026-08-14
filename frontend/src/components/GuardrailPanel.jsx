import { GUARDRAIL_CHECKLIST, groupChecklist } from "../data/guardrailChecklist";

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
  const groups = groupChecklist(GUARDRAIL_CHECKLIST);

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
