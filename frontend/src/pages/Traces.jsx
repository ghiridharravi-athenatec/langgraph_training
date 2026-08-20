import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import ToolCallLog from "../components/ToolCallLog";
import { GUARDRAIL_CHECKLIST, DATABASE_GUARDRAIL_CHECKLIST, resolveBlockedGuardrailLabel } from "../data/guardrailChecklist";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";

const TABS = [
  { id: "users", label: "Users", icon: "◒" },
  { id: "guardrails", label: "Guardrails", icon: "▣" },
  { id: "tracing", label: "Tracing", icon: "≋" },
];

function formatDate(value) {
  return new Date(value).toLocaleString();
}

function Breadcrumb({ items }) {
  return (
    <div className="trace-breadcrumb">
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={i} className="trace-breadcrumb-part">
            {i > 0 && <span className="trace-breadcrumb-sep">/</span>}
            {isLast || !item.onClick ? (
              <span className="trace-breadcrumb-current">{item.label}</span>
            ) : (
              <button type="button" className="trace-breadcrumb-link" onClick={item.onClick}>
                {item.label}
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users tab - the full roster, with each user's conversation count.
// ---------------------------------------------------------------------------

function UsersTab() {
  const { isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/traces/users")
      .then(({ data }) => {
        setUsers(data);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load users."));
        setStatus("error");
      });
  }, []);

  return (
    <div className="traces-page">
      <div className="traces-page-header">
        <h1>Users</h1>
        <p className="muted">
          {isAdmin ? "Everyone with access to this workspace." : "Your account."}
        </p>
      </div>

      {status === "loading" && <p className="muted">Loading…</p>}
      {status === "error" && <p className="form-error">{error}</p>}

      {status === "ready" && (
        <div className="table-scroll">
          <table className="permission-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Conversations</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>
                    <span className={`role-badge ${u.role === "admin" ? "role-badge-admin" : ""}`}>{u.role}</span>
                  </td>
                  <td>{u.conversation_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Guardrails tab - live, editable thresholds ("rubrics") on top, the static
// catalog of every check in the pipeline below.
// ---------------------------------------------------------------------------

const PII_ENTITY_OPTIONS = [
  { value: "EMAIL_ADDRESS", label: "Email address" },
  { value: "PHONE_NUMBER", label: "Phone number" },
  { value: "CREDIT_CARD", label: "Credit card" },
  { value: "US_SSN", label: "SSN" },
  { value: "US_BANK_NUMBER", label: "Bank account number" },
  { value: "US_DRIVER_LICENSE", label: "Driver's license" },
  { value: "US_PASSPORT", label: "Passport number" },
  { value: "IBAN_CODE", label: "IBAN" },
  { value: "IP_ADDRESS", label: "IP address" },
  { value: "CRYPTO", label: "Crypto wallet address" },
  { value: "PERSON", label: "Person name" },
  { value: "LOCATION", label: "Location" },
  { value: "NRP", label: "Nationality / religious / political group" },
  { value: "MEDICAL_LICENSE", label: "Medical license" },
];

const HARM_CATEGORY_OPTIONS = [
  { value: "HARM_CATEGORY_HARASSMENT", label: "Harassment" },
  { value: "HARM_CATEGORY_HATE_SPEECH", label: "Hate speech" },
  { value: "HARM_CATEGORY_SEXUALLY_EXPLICIT", label: "Sexually explicit" },
  { value: "HARM_CATEGORY_DANGEROUS_CONTENT", label: "Dangerous content" },
];

const SAFETY_THRESHOLD_OPTIONS = [
  { value: "BLOCK_NONE", label: "Never block" },
  { value: "BLOCK_ONLY_HIGH", label: "Only high severity" },
  { value: "BLOCK_MEDIUM_AND_ABOVE", label: "Medium and above" },
  { value: "BLOCK_LOW_AND_ABOVE", label: "Low and above (strictest)" },
];

// PII detection is a separate, independently-tunable config for input
// (question) vs. output (answer) - see INPUT_PII_DETECTION_GROUP /
// OUTPUT_PII_DETECTION_GROUP below. Model safety still governs both stages
// through one shared config key, so that group object is reused as-is under
// both categories - editing it in one place edits the same config key
// everywhere it appears. (Document ingestion has its own separate PII policy
// too, but that lives on the Data Ingestion upload screen, not here.)
const INPUT_LENGTH_GROUP = {
  name: "Input",
  fields: [
    { key: "min_question_length", label: "Minimum question length", type: "number", min: 0, max: 500 },
    { key: "max_question_length", label: "Maximum question length", type: "number", min: 10, max: 20000 },
    {
      key: "blocked_keywords",
      label: "Blocked keywords",
      type: "tags",
      hint: "Checked on both the question and the generated answer.",
    },
  ],
};

const QUOTA_GROUP = {
  name: "Quota",
  // Only field here is the global default - per-user overrides are a separate,
  // admin-only control (UserQuotaEditor, rendered above these fields for admins
  // only). Without this field the card was entirely empty for non-admins, since
  // UserQuotaEditor never renders for them.
  fields: [
    {
      key: "daily_token_quota",
      label: "Default daily token quota",
      type: "number",
      min: 0,
      max: 100000000,
      step: 1000,
      hint: "Applies to every user unless overridden per-user below (admin only).",
    },
  ],
};

const INPUT_PII_DETECTION_GROUP = {
  name: "PII detection",
  fields: [
    {
      key: "input_pii_entities",
      label: "Entity types to detect",
      type: "checkboxes",
      options: PII_ENTITY_OPTIONS,
      hint: "Applies to the incoming question only.",
    },
    { key: "input_pii_score_threshold", label: "Detection confidence threshold", type: "score" },
  ],
};

const OUTPUT_PII_DETECTION_GROUP = {
  name: "PII detection",
  fields: [
    {
      key: "output_pii_entities",
      label: "Entity types to detect",
      type: "checkboxes",
      options: PII_ENTITY_OPTIONS,
      hint: "Applies to the generated answer only.",
    },
    { key: "output_pii_score_threshold", label: "Detection confidence threshold", type: "score" },
  ],
};

const MODEL_SAFETY_GROUP = {
  name: "Model safety",
  fields: [
    {
      key: "model_safety_categories",
      label: "Harm categories checked",
      type: "checkboxes",
      options: HARM_CATEGORY_OPTIONS,
      hint: "Applies to both the question and the generated answer.",
    },
    { key: "model_safety_threshold", label: "Block threshold", type: "select", options: SAFETY_THRESHOLD_OPTIONS },
  ],
};

const INTENT_GROUP = {
  name: "Intent",
  fields: [{ key: "intent_confidence_threshold", label: "Minimum confidence to route", type: "score" }],
};

const TOPIC_RESTRICTION_GROUP = {
  name: "Topic restriction",
  fields: [
    {
      key: "allowed_topics",
      label: "Approved topics",
      type: "tags",
      hint: "Empty means no topic restriction is applied. Judged by the model alongside intent classification.",
    },
  ],
};

const SEMANTIC_CACHE_GROUP = {
  name: "Semantic cache",
  fields: [
    { key: "semantic_cache_similarity_threshold", label: "Similarity threshold", type: "score" },
    { key: "semantic_cache_max_candidates", label: "Max candidates checked", type: "number", min: 1, max: 2000 },
  ],
};

const RETRIEVAL_RELEVANCE_GROUP = {
  name: "Retrieval relevance",
  fields: [
    { key: "min_relevance_score", label: "Minimum relevance score", type: "score" },
    { key: "max_context_chunks", label: "Max chunks kept", type: "number", min: 1, max: 100 },
  ],
};

const DOCUMENT_ROUTING_GROUP = {
  name: "Document routing",
  fields: [
    {
      key: "document_routing_enabled",
      label: "Enabled",
      type: "boolean",
      hint: "Narrows retrieval to the document(s) a question is confidently about, for users with more than one upload. Never blocks - disabled (or unconfident) means search everything, exactly like before this existed.",
    },
    {
      key: "document_routing_min_score",
      label: "Confidence floor",
      type: "score",
      hint: "Fraction of the question's words that must appear in a document for it to be routed to. Below this, every document is searched.",
    },
  ],
};

const CONTEXT_BUDGET_GROUP = {
  name: "Context budget",
  fields: [
    { key: "max_context_chars", label: "Context budget (characters)", type: "number", min: 500, max: 200000, step: 500 },
  ],
};

const ANSWER_QUALITY_GROUP = {
  name: "Answer quality",
  fields: [{ key: "min_groundedness_score", label: "Minimum groundedness score", type: "score" }],
};

const OUTPUT_GROUP = {
  name: "Output",
  fields: [
    { key: "allowed_url_domains", label: "Allowed link domains", type: "tags", hint: "Empty means no links are allowed at all." },
    { key: "max_answer_length", label: "Maximum answer length", type: "number", min: 100, max: 50000, step: 100 },
  ],
};

const COMPLIANCE_GROUP = {
  name: "Compliance",
  fields: [
    {
      key: "compliance_keywords",
      label: "Regulated-claim phrases",
      type: "tags",
      hint: "Checked on the generated answer; blocks the response if matched.",
    },
  ],
};

const TONE_GROUP = {
  name: "Tone calibration",
  fields: [
    {
      key: "tone_calibration_enabled",
      label: "Enabled",
      type: "boolean",
      hint: "Flags informal phrasing (shouting punctuation, slang) in the answer without blocking it.",
    },
  ],
};

const BIAS_GROUP = {
  name: "Bias detection",
  fields: [
    {
      key: "bias_detection_enabled",
      label: "Enabled",
      type: "boolean",
      hint: "Model self-reports unfair characterization in its own answer, riding on the answer-generation call; blocks if flagged.",
    },
  ],
};

const INDIRECT_INJECTION_GROUP = {
  name: "Indirect context injection",
  fields: [
    {
      key: "indirect_injection_detection_enabled",
      label: "Enabled",
      type: "boolean",
      hint: "A dedicated, small/fast classifier call scores every retrieved chunk for text addressed to the AI assistant before the answering call ever sees them. Doesn't block the turn - flagged chunks are excluded from context and reported in the trace, with a notice appended to the answer.",
    },
    {
      key: "indirect_injection_confidence_threshold",
      label: "Confidence threshold to exclude",
      type: "score",
      hint: "Minimum classifier confidence a flagged chunk must clear to actually be excluded from context.",
    },
  ],
};

// Display-only relabeling - internal category identifiers ("Input"/"Output")
// stay as-is everywhere else (guardrailChecklist.js's category field, CSS,
// etc.), only the on-screen text changes to match the pipeline's actual
// request -> retrieval -> response framing.
const CATEGORY_LABELS = {
  Input: "Request",
  Retrieval: "Retrieval",
  Output: "Response",
};

// Maps each catalog check (guardrailChecklist.js, by id) to the live config
// field(s) that tune it, if any. A check with no entry here has no adjustable
// threshold - its behavior is fixed in code (e.g. a regex pattern, a schema
// parse). model_input_validation/model_output_validation intentionally share
// MODEL_SAFETY_GROUP - one config key governs the same Gemini safety check at
// both stages. blocked_keywords is likewise shared between the input and
// output checks that both read it.
const ITEM_ADJUSTABLE_FIELDS = {
  "input.length": [INPUT_LENGTH_GROUP.fields[0], INPUT_LENGTH_GROUP.fields[1]],
  "input.blocked_keywords": [INPUT_LENGTH_GROUP.fields[2]],
  "input.pii_masking": INPUT_PII_DETECTION_GROUP.fields,
  quota_check: QUOTA_GROUP.fields,
  model_input_validation: MODEL_SAFETY_GROUP.fields,
  intent_detection: INTENT_GROUP.fields,
  topic_restriction: TOPIC_RESTRICTION_GROUP.fields,
  document_routing: DOCUMENT_ROUTING_GROUP.fields,
  semantic_cache: SEMANTIC_CACHE_GROUP.fields,
  retrieval_validation: RETRIEVAL_RELEVANCE_GROUP.fields,
  context_budget: CONTEXT_BUDGET_GROUP.fields,
  model_output_validation: MODEL_SAFETY_GROUP.fields,
  groundedness_check: ANSWER_QUALITY_GROUP.fields,
  bias_detection: BIAS_GROUP.fields,
  context_injection_filter: INDIRECT_INJECTION_GROUP.fields,
  "output.blocked_keywords": [INPUT_LENGTH_GROUP.fields[2]],
  "output.compliance_validation": COMPLIANCE_GROUP.fields,
  "output.pii_masking": OUTPUT_PII_DETECTION_GROUP.fields,
  "output.url_allowlist": [OUTPUT_GROUP.fields[0]],
  "output.length_limit": [OUTPUT_GROUP.fields[1]],
  "output.tone_check": TONE_GROUP.fields,
};

// Every catalog check, Input -> Retrieval -> Output, each carrying its
// adjustable field list (empty for fixed/non-configurable checks).
const GUARDRAIL_ROWS_BY_CATEGORY = ["Input", "Retrieval", "Output"]
  .map((category) => ({
    name: category,
    items: GUARDRAIL_CHECKLIST.filter((item) => item.category === category).map((item) => ({
      ...item,
      fields: ITEM_ADJUSTABLE_FIELDS[item.id] || [],
    })),
  }))
  .filter((cat) => cat.items.length > 0);

const FILTER_TABS = [
  { id: "all", label: "All" },
  { id: "adjustable", label: "Adjustable" },
  { id: "fixed", label: "Fixed" },
];

function NumberField({ field, value, onChange, disabled }) {
  return (
    <input
      type="number"
      min={field.min}
      max={field.max}
      step={field.step || 1}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

function ScoreField({ value, onChange, disabled }) {
  return (
    <div className="gr-score-row">
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="gr-score-value">{Number(value).toFixed(2)}</span>
    </div>
  );
}

function TagsField({ value, onChange, disabled }) {
  const [draft, setDraft] = useState("");

  function addTag() {
    const cleaned = draft.trim().toLowerCase();
    if (!cleaned || value.includes(cleaned)) {
      setDraft("");
      return;
    }
    onChange([...value, cleaned]);
    setDraft("");
  }

  return (
    <div className="gr-tags">
      <div className="gr-tag-list">
        {value.length === 0 && <span className="gr-tag-empty">None</span>}
        {value.map((tag) => (
          <span key={tag} className="guardrail-badge gr-tag">
            {tag}
            {!disabled && (
              <button type="button" className="gr-tag-remove" onClick={() => onChange(value.filter((t) => t !== tag))}>
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      {!disabled && (
        <div className="gr-tag-input-row">
          <input
            type="text"
            value={draft}
            placeholder="Add and press Enter…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addTag();
              }
            }}
          />
          <button type="button" className="btn-secondary" onClick={addTag}>
            Add
          </button>
        </div>
      )}
    </div>
  );
}

function BooleanField({ value, onChange, disabled }) {
  return (
    <label className="gr-checkbox-row">
      <input type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {value ? "Enabled" : "Disabled"}
    </label>
  );
}

function CheckboxesField({ field, value, onChange, disabled }) {
  return (
    <div className="gr-checkboxes">
      {field.options.map((opt) => (
        <label key={opt.value} className="gr-checkbox-row">
          <input
            type="checkbox"
            checked={value.includes(opt.value)}
            disabled={disabled}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, opt.value] : value.filter((v) => v !== opt.value))
            }
          />
          {opt.label}
        </label>
      ))}
    </div>
  );
}

function SelectField({ field, value, onChange, disabled }) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      {field.options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

function ConfigField({ field, value, onChange, disabled }) {
  switch (field.type) {
    case "number":
      return <NumberField field={field} value={value} onChange={onChange} disabled={disabled} />;
    case "score":
      return <ScoreField value={value} onChange={onChange} disabled={disabled} />;
    case "tags":
      return <TagsField value={value} onChange={onChange} disabled={disabled} />;
    case "checkboxes":
      return <CheckboxesField field={field} value={value} onChange={onChange} disabled={disabled} />;
    case "select":
      return <SelectField field={field} value={value} onChange={onChange} disabled={disabled} />;
    case "boolean":
      return <BooleanField value={value} onChange={onChange} disabled={disabled} />;
    default:
      return null;
  }
}

function UserQuotaEditor({ globalDefault }) {
  const [users, setUsers] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

  useEffect(() => {
    api
      .get("/admin/users")
      .then(({ data }) => {
        setUsers(data);
        if (data.length > 0) setSelectedId(data[0].id);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load users."));
        setStatus("error");
      });
  }, []);

  const selectedUser = users.find((u) => u.id === selectedId) || null;
  const hasOverride =
    !!selectedUser && selectedUser.daily_token_quota !== null && selectedUser.daily_token_quota !== undefined;

  useEffect(() => {
    if (selectedUser) {
      setDraft(hasOverride ? String(selectedUser.daily_token_quota) : String(globalDefault));
      setSaveMessage(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function persistQuota(quota) {
    if (!selectedUser) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const { data } = await api.put(`/admin/users/${selectedUser.id}/quota`, { daily_token_quota: quota });
      setUsers((prev) => prev.map((u) => (u.id === data.id ? data : u)));
      return true;
    } catch (err) {
      setSaveMessage({ ok: false, text: formatErrorDetail(err, "Failed to update quota.") });
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    const raw = draft.trim();
    const quota = raw === "" ? null : Number(raw);
    if (quota !== null && (!Number.isFinite(quota) || quota < 0)) {
      setSaveMessage({ ok: false, text: "Quota must be a non-negative number." });
      return;
    }
    if (await persistQuota(quota)) {
      setSaveMessage({ ok: true, text: "Saved." });
    }
  }

  async function handleResetToDefault() {
    if (await persistQuota(null)) {
      setDraft(String(globalDefault));
      setSaveMessage({ ok: true, text: "Reset to default." });
    }
  }

  if (status === "loading") return <p className="muted">Loading users…</p>;
  if (status === "error") return <p className="form-error">{error}</p>;

  return (
    <div className="gr-user-quota">
      <div className="gr-field">
        <span className="field-label">User</span>
        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.email}
              {user.role === "admin" ? " (admin)" : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="gr-field">
        <span className="field-label">Daily token quota</span>
        <input
          type="number"
          min={0}
          value={draft}
          disabled={saving || !selectedUser}
          onChange={(e) => setDraft(e.target.value)}
        />
        <span className="gr-field-hint">
          {hasOverride
            ? "Custom quota for this user."
            : `Using the default (${Number(globalDefault).toLocaleString()}) - every user starts here unless overridden, admins included.`}
        </span>
      </div>
      <div className="gr-config-actions">
        <button className="btn-primary" onClick={handleSave} disabled={saving || !selectedUser}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="btn-secondary" onClick={handleResetToDefault} disabled={saving || !selectedUser || !hasOverride}>
          Reset to default
        </button>
        {saveMessage && (
          <span className={saveMessage.ok ? "sidebar-status-ok" : "sidebar-status-error"}>{saveMessage.text}</span>
        )}
      </div>
    </div>
  );
}

function GuardrailsTab() {
  const { isAdmin } = useAuth();

  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);
  const [filterTab, setFilterTab] = useState("all");

  useEffect(() => {
    api
      .get("/traces/guardrail-config")
      .then(({ data }) => {
        setConfig(data);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load guardrail settings."));
        setStatus("error");
      });
  }, []);

  function setField(key, value) {
    setConfig((prev) => ({ ...prev, [key]: value }));
    setSaveMessage(null);
  }

  async function handleSave() {
    setSaving(true);
    setSaveMessage(null);
    try {
      const { data } = await api.put("/traces/guardrail-config", config);
      setConfig(data);
      setSaveMessage({ ok: true, text: "Saved. Takes effect on the very next request." });
    } catch (err) {
      setSaveMessage({ ok: false, text: formatErrorDetail(err, "Failed to save.") });
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setSaving(true);
    setSaveMessage(null);
    try {
      const { data } = await api.post("/traces/guardrail-config/reset");
      setConfig(data);
      setSaveMessage({ ok: true, text: "Reset to defaults." });
    } catch (err) {
      setSaveMessage({ ok: false, text: formatErrorDetail(err, "Failed to reset.") });
    } finally {
      setSaving(false);
    }
  }

  const visibleCategories = GUARDRAIL_ROWS_BY_CATEGORY.map((category) => ({
    ...category,
    items: category.items.filter((item) => {
      if (filterTab === "adjustable") return item.fields.length > 0;
      if (filterTab === "fixed") return item.fields.length === 0;
      return true;
    }),
  })).filter((category) => category.items.length > 0);

  return (
    <div className="traces-page">
      <div className="traces-page-header">
        <h1>Guardrails</h1>
        <p className="muted">
          {isAdmin
            ? "Every check in the pipeline. Tune what's adjustable below - the rest is fixed in code."
            : "Every check in the pipeline, and the thresholds behind it. Ask an admin to change a value."}
        </p>
      </div>

      {status === "loading" && <p className="muted">Loading…</p>}
      {status === "error" && <p className="form-error">{error}</p>}

      {status === "ready" && config && (
        <div className="gr-config">
          {!isAdmin && (
            <p className="gr-readonly-note">You have read-only access to these settings.</p>
          )}

          <div className="segmented-toggle gr-tab-switch">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={filterTab === tab.id ? "segmented-toggle-active" : ""}
                onClick={() => setFilterTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="traces-guardrail-catalog">
            {visibleCategories.map((category) => (
              <div key={category.name} className="gr-category-section">
                <h3 className="gr-category-heading">{CATEGORY_LABELS[category.name] || category.name}</h3>
                <div className="gr-row-list">
                  {category.items.map((item) => (
                    <div key={item.id} className={`gr-row ${item.fields.length ? "gr-row-adjustable" : "gr-row-fixed"}`}>
                      <div className="gr-row-header">
                        <span className="gr-row-name">{item.label}</span>
                        <span className={`gr-row-badge ${item.fields.length ? "gr-row-badge-adjustable" : "gr-row-badge-fixed"}`}>
                          {item.fields.length ? "Adjustable" : "Fixed"}
                        </span>
                      </div>
                      <p className="gr-row-desc">{item.description}</p>

                      {item.fields.length > 0 && (
                        <div className="gr-row-fields">
                          {item.fields.map((field) => (
                            <div key={field.key} className="gr-field-row">
                              <span className="gr-field-row-label">{field.label}</span>
                              <div className="gr-field-row-control">
                                <ConfigField
                                  field={field}
                                  value={config[field.key]}
                                  onChange={(v) => setField(field.key, v)}
                                  disabled={!isAdmin}
                                />
                                {field.hint && <span className="gr-field-hint">{field.hint}</span>}
                              </div>
                            </div>
                          ))}
                          {item.id === "quota_check" && isAdmin && (
                            <div className="gr-row-quota-override">
                              <span className="field-label">Per-user override</span>
                              <UserQuotaEditor globalDefault={config.daily_token_quota} />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {isAdmin && (
            <div className="gr-config-actions">
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </button>
              <button className="btn-secondary" onClick={handleReset} disabled={saving}>
                Reset to defaults
              </button>
              {saveMessage && (
                <span className={saveMessage.ok ? "sidebar-status-ok" : "sidebar-status-error"}>{saveMessage.text}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tracing tab - drill down: users -> that user's conversations -> full trace.
// ---------------------------------------------------------------------------

function TracingUsers({ onSelectUser, projectId }) {
  const [users, setUsers] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get("/traces/users", { params: { project_id: projectId } })
      .then(({ data }) => {
        setUsers(data);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load users."));
        setStatus("error");
      });
  }, []);

  return (
    <div className="traces-page">
      <div className="traces-page-header">
        <h1>Tracing</h1>
        <p className="muted">Pick a user to see their conversations and guardrail traces.</p>
      </div>

      {status === "loading" && <p className="muted">Loading…</p>}
      {status === "error" && <p className="form-error">{error}</p>}

      {status === "ready" && users.length === 0 && (
        <div className="empty-state">
          <p>No users yet.</p>
        </div>
      )}

      {status === "ready" && users.length > 0 && (
        <div className="trace-list">
          {users.map((u) => (
            <button key={u.id} type="button" className="trace-list-item" onClick={() => onSelectUser(u)}>
              <div className="trace-list-item-main">
                <span className="trace-list-item-title">{u.email}</span>
                <span className="trace-list-item-sub">
                  <span className={`role-badge ${u.role === "admin" ? "role-badge-admin" : ""}`}>{u.role}</span>
                </span>
              </div>
              <div className="trace-list-item-meta">
                <span className="trace-count-badge">
                  {u.conversation_count} conversation{u.conversation_count === 1 ? "" : "s"}
                </span>
                <span aria-hidden="true">→</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function truncate(text, max = 90) {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

// Flat, Langfuse-style trace list: every question this user has asked, newest
// first, across every conversation - not grouped by conversation.
function TracingUserQuestions({ user, onSelectTurn, onBack, projectId }) {
  const [turns, setTurns] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    setStatus("loading");
    api
      .get(`/traces/users/${user.id}/turns`, { params: { project_id: projectId } })
      .then(({ data }) => {
        setTurns(data);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load questions."));
        setStatus("error");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);

  return (
    <div className="traces-page">
      <Breadcrumb items={[{ label: "Tracing", onClick: onBack }, { label: user.email }]} />

      <div className="traces-page-header">
        <h1>{user.email}</h1>
        <p className="muted">Every question this user has asked, newest first. Click one for its full guardrail trace.</p>
      </div>

      {status === "loading" && <p className="muted">Loading…</p>}
      {status === "error" && <p className="form-error">{error}</p>}

      {status === "ready" && turns.length === 0 && (
        <div className="empty-state">
          <p>No questions yet.</p>
        </div>
      )}

      {status === "ready" && turns.length > 0 && (
        <div className="table-scroll">
          <table className="permission-table trace-turn-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Question</th>
                <th>Response time</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {turns.map((t) => (
                <tr key={t.id} className="trace-turn-row" onClick={() => onSelectTurn(t)}>
                  <td className="trace-turn-time">{formatDate(t.created_at)}</td>
                  <td className="trace-turn-question">{truncate(t.question)}</td>
                  <td className="trace-turn-time">{formatResponseTime(t.response_time_ms) ?? "—"}</td>
                  <td>
                    <div className="trace-turn-status">
                      {t.cached && <span className="guardrail-badge guardrail-badge-pii">Cached</span>}
                      {t.blocked && <span className="guardrail-badge guardrail-badge-warn">Blocked</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Detail for one question: the answer plus its full guardrail trace.
function TracingTurnDetail({ user, turn, onBackToUsers, onBackToQuestions }) {
  return (
    <div className="traces-page">
      <Breadcrumb
        items={[
          { label: "Tracing", onClick: onBackToUsers },
          { label: user.email, onClick: onBackToQuestions },
          { label: truncate(turn.question, 40) },
        ]}
      />

      <div className="traces-page-header">
        <h1>{truncate(turn.question, 80)}</h1>
        <p className="muted">
          Asked {formatDate(turn.created_at)}
          {turn.response_time_ms != null && ` · Answered in ${formatResponseTime(turn.response_time_ms)}`}
        </p>
      </div>

      <div className="trace-detail">
        <div className="trace-field">
          <div className="trace-field-head">
            <span className="field-label">User prompt</span>
          </div>
          <div className="trace-field-box">{turn.question}</div>
        </div>

        <div className="trace-field">
          <div className="trace-field-head">
            <span className="field-label">Answer</span>
            {turn.blocked && (
              <span className="guardrail-badge guardrail-badge-warn">
                Blocked{(() => {
                  const label = resolveBlockedGuardrailLabel(turn.graph_response?.guardrail_events || turn.guardrail_events);
                  return label ? ` - ${label}` : "";
                })()}
              </span>
            )}
            {turn.cached && <span className="guardrail-badge guardrail-badge-pii">Cached answer</span>}
          </div>
          <div className="trace-field-box">
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatPiiTokens(turn.answer)}</ReactMarkdown>
            </div>
          </div>
        </div>

        {turn.graph_response ? (
          (turn.logs?.length > 0 || turn.graph_response) && (
            <GuardrailPanel logs={turn.logs} graphResponse={turn.graph_response} />
          )
        ) : (
          (turn.guardrail_events?.length > 0 || turn.logs?.length > 0) && (
            <>
              <GuardrailPanel logs={turn.logs} events={turn.guardrail_events} checklist={DATABASE_GUARDRAIL_CHECKLIST} />
              <ToolCallLog events={turn.guardrail_events} />
            </>
          )
        )}
      </div>
    </div>
  );
}

export function TracingTab({ projectId, initialTurnId, onConsumedInitialTurn } = {}) {
  const { isAdmin, user: authUser } = useAuth();
  const [selectedUser, setSelectedUser] = useState(null);
  const [selectedTurn, setSelectedTurn] = useState(null);
  const [deepLinkStatus, setDeepLinkStatus] = useState(initialTurnId ? "loading" : "idle");
  const [deepLinkError, setDeepLinkError] = useState("");

  // "View Trace" from a chat answer - jump straight to that turn's detail (always
  // the current user's own, admin or not), skipping the user-list/question-list
  // steps entirely. Single-turn fetch (GET /traces/turns/{id}) rather than pulling
  // the user's whole trace list just to find one row.
  useEffect(() => {
    if (!initialTurnId) return;
    setDeepLinkStatus("loading");
    setDeepLinkError("");
    api
      .get(`/traces/turns/${initialTurnId}`)
      .then(({ data }) => {
        setSelectedUser(authUser ? { id: authUser.id, email: authUser.email } : null);
        setSelectedTurn(data);
        setDeepLinkStatus("idle");
        onConsumedInitialTurn?.();
      })
      .catch((err) => {
        setDeepLinkError(formatErrorDetail(err, "Failed to load this trace."));
        setDeepLinkStatus("error");
        onConsumedInitialTurn?.();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTurnId]);

  // A non-admin only ever has themselves to pick - the backend only returns their own
  // tracing data anyway (see traces.py's _ensure_self_or_admin), so skip the "pick a
  // user" step entirely instead of showing a one-row list to click through.
  const effectiveUser = isAdmin
    ? selectedUser
    : selectedUser || (authUser ? { id: authUser.id, email: authUser.email } : null);

  if (deepLinkStatus === "loading") {
    return (
      <div className="traces-page">
        <p className="muted">Loading trace…</p>
      </div>
    );
  }

  if (deepLinkStatus === "error") {
    return (
      <div className="traces-page">
        <p className="form-error">{deepLinkError}</p>
      </div>
    );
  }

  if (effectiveUser && selectedTurn) {
    return (
      <TracingTurnDetail
        user={effectiveUser}
        turn={selectedTurn}
        onBackToUsers={
          isAdmin
            ? () => {
                setSelectedUser(null);
                setSelectedTurn(null);
              }
            : undefined
        }
        onBackToQuestions={() => setSelectedTurn(null)}
      />
    );
  }

  if (effectiveUser) {
    return (
      <TracingUserQuestions
        user={effectiveUser}
        onSelectTurn={setSelectedTurn}
        onBack={isAdmin ? () => setSelectedUser(null) : undefined}
        projectId={projectId}
      />
    );
  }

  return <TracingUsers onSelectUser={setSelectedUser} projectId={projectId} />;
}

// ---------------------------------------------------------------------------
// Project shell - Langfuse-style: dark sidebar of tabs, light content area.
// ---------------------------------------------------------------------------

export default function TracesProject() {
  const { user, logout } = useAuth();
  const [activeTab, setActiveTab] = useState("users");

  return (
    <div className="traces-shell">
      <aside className="traces-sidebar">
        <Link to="/" className="traces-brand">
          <span className="brand-mark">✦</span>
          <span>AI Guardrails</span>
        </Link>

        <div className="traces-project-name">
          <span className="traces-project-icon">◆</span> Traces
        </div>

        <nav className="traces-nav">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`traces-nav-item ${activeTab === tab.id ? "traces-nav-item-active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="traces-nav-icon">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="traces-sidebar-footer">
          <span className="traces-account-email">{user?.email}</span>
          <button className="btn-ghost" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>

      <main className="traces-main">
        {activeTab === "users" && <UsersTab />}
        {activeTab === "guardrails" && <GuardrailsTab />}
        {activeTab === "tracing" && <TracingTab />}
      </main>
    </div>
  );
}
