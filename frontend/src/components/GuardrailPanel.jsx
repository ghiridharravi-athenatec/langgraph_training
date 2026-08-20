import { GUARDRAIL_CHECKLIST } from "../data/guardrailChecklist";

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

// Same Input -> Retrieval -> Output staging as the Guardrails tab's config
// view, relabeled to match the pipeline's actual request -> retrieval ->
// response framing.
const CATEGORY_LABELS = {
  Input: "Request",
  Retrieval: "Retrieval",
  Output: "Response",
};

function groupByCategory(checklist) {
  return ["Input", "Retrieval", "Output"]
    .map((category) => ({ name: category, items: checklist.filter((item) => item.category === category) }))
    .filter((group) => group.items.length > 0);
}

const STATUS_META = {
  pass: { icon: "✓", label: "Passed" },
  fail: { icon: "✗", label: "Blocked" },
  skipped: { icon: "⏭", label: "Skipped" },
  not_run: { icon: "–", label: "Not run" },
};

function GuardrailTableRow({ item, events }) {
  const result = item.resolve(events);
  const meta = STATUS_META[result.status];
  const piiDetected = result.piiDetected || [];
  const flaggedCategories = result.flaggedCategories || [];

  // Every field below except "reason" (its own column) - kept as a flat list of
  // {label, node} pairs, same as before, so the Details column can render whatever
  // subset applies to this particular check with consistent inline formatting.
  const detailFields = [];
  if (piiDetected.length > 0) {
    detailFields.push({
      label: "Masked",
      node: piiDetected.map((p) => (
        <span key={p.entity_type} className="guardrail-badge guardrail-badge-pii">
          {piiLabel(p.entity_type)}
          {p.count > 1 ? ` ×${p.count}` : ""}
        </span>
      )),
    });
  }
  if (flaggedCategories.length > 0) {
    detailFields.push({
      label: "Flagged",
      node: flaggedCategories.map((c) => (
        <span key={c} className="guardrail-badge guardrail-badge-warn">
          {c.replace("HARM_CATEGORY_", "").replaceAll("_", " ").toLowerCase()}
        </span>
      )),
    });
  }
  if (result.intent !== undefined) {
    detailFields.push({
      label: result.status === "pass" ? "Detected" : "Best guess",
      node: (
        <span className={`guardrail-badge ${result.status === "pass" ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
          {result.intent}
          {typeof result.confidence === "number" ? ` (${Math.round(result.confidence * 100)}%)` : ""}
        </span>
      ),
    });
  }
  if (typeof result.tokensUsedToday === "number") {
    detailFields.push({
      label: "Usage",
      node: (
        <span className="guardrail-badge">
          {result.tokensUsedToday.toLocaleString()} / {result.dailyQuota?.toLocaleString()} tokens today
        </span>
      ),
    });
  }
  if (typeof result.groundednessScore === "number") {
    detailFields.push({
      label: "Similarity",
      node: (
        <span className={`guardrail-badge ${result.status === "pass" ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
          {result.groundednessScore.toFixed(2)}
        </span>
      ),
    });
  }
  if (typeof result.cacheHit === "boolean") {
    detailFields.push({
      label: result.cacheHit ? "Reused" : "Cache",
      node: (
        <span className={`guardrail-badge ${result.cacheHit ? "guardrail-badge-pii" : ""}`}>
          {result.cacheHit
            ? `"${result.matchedQuestion}" (similarity ${result.cacheSimilarity?.toFixed(2)})`
            : "No similar past question found"}
        </span>
      ),
    });
  }
  if (typeof result.checkedCount === "number") {
    detailFields.push({
      label: "Checked",
      node: (
        <span className={`guardrail-badge ${result.excludedCount ? "guardrail-badge-warn" : "guardrail-badge-pii"}`}>
          {result.excludedCount || 0} of {result.checkedCount} chunk(s) excluded
        </span>
      ),
    });
  }
  if (result.flaggedChunks?.length > 0) {
    detailFields.push({
      label: "Flagged chunks",
      node: result.flaggedChunks.map((chunk, i) => (
        <span key={i} className="guardrail-badge guardrail-badge-warn" title={chunk.reasoning || ""}>
          <code className="gr-inline-code">{chunk.source}</code> ({Math.round((chunk.confidence || 0) * 100)}%)
        </span>
      )),
    });
  }
  if (result.action) {
    detailFields.push({ label: "Action", node: <span className="guardrail-badge">{result.action}</span> });
  }

  return (
    <tr className={`gr-trow gr-trow-status-${result.status}`}>
      <td className="gr-td gr-td-check">
        <div className="gr-td-check-name">{item.label}</div>
        <div className="gr-td-check-desc">{item.description}</div>
      </td>
      <td className="gr-td gr-td-status">
        <span className={`gr-row-badge gr-row-badge-${result.status}`}>
          {meta.icon} {meta.label}
        </span>
      </td>
      <td className="gr-td gr-td-reason">
        {result.reason || <span className="gr-td-empty">—</span>}
      </td>
      <td className="gr-td gr-td-details">
        {detailFields.length > 0 ? (
          <div className="gr-td-details-list">
            {detailFields.map((field, i) => (
              <div key={i} className="gr-detail-item">
                <span className="gr-detail-label">{field.label}:</span>
                {field.node}
              </div>
            ))}
          </div>
        ) : (
          <span className="gr-td-empty">—</span>
        )}
      </td>
    </tr>
  );
}

export default function GuardrailPanel({ logs, graphResponse, events: eventsProp, checklist }) {
  // graphResponse is the document pipeline's envelope; database-chatbot turns
  // pass events directly instead (see app/api/v1/database.py - there's no
  // graph_response for them, just a flat guardrail_events list on the message).
  const events = eventsProp || graphResponse?.guardrail_events || [];
  const categories = groupByCategory(checklist || GUARDRAIL_CHECKLIST);

  return (
    <div className="trace-field">
      <div className="trace-field-head">
        <span className="field-label">Guardrail checks</span>
      </div>

      <div className="traces-guardrail-catalog">
        {categories.map((category) => (
          <div key={category.name} className="gr-category-section">
            <h4 className="gr-category-heading">{CATEGORY_LABELS[category.name] || category.name}</h4>
            <div className="gr-table-wrap">
              <table className="gr-table">
                <thead>
                  <tr>
                    <th className="gr-th-check">Check</th>
                    <th className="gr-th-status">Status</th>
                    <th className="gr-th-reason">Reason</th>
                    <th className="gr-th-details">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {category.items.map((item) => (
                    <GuardrailTableRow key={item.id} item={item} events={events} />
                  ))}
                </tbody>
              </table>
            </div>
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
