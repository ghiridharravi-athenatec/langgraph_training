import { useEffect, useState } from "react";
import api, { formatErrorDetail } from "../api/client";

// Human-readable labels for the entity type names GET /ingest/pii-options returns -
// same catalog as PII_ENTITY_OPTIONS on the Guardrails page, kept separate since
// this component doesn't import from Traces.jsx.
const PII_ENTITY_LABELS = {
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

// Document upload form - shared by RagChatbot.jsx and AssistantChat.jsx's "Data
// Ingestion" sections, since both answer from the same user-scoped documents (see
// app/api/v1/documents.py - there's no per-project tagging, only a permission gate).
// onIngested is called after a successful upload so a caller with its own
// "has documents" banner state (RagChatbot's chat tab) can refresh it.
export default function IngestPanel({ onIngested } = {}) {
  const [file, setFile] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingesting, setIngesting] = useState(false);
  const [piiOptions, setPiiOptions] = useState([]);
  const [selectedPiiEntities, setSelectedPiiEntities] = useState([]);

  useEffect(() => {
    loadPiiOptions();
  }, []);

  async function loadPiiOptions() {
    try {
      const { data } = await api.get("/ingest/pii-options");
      const options = data.available_entities.map((value) => ({
        value,
        label: PII_ENTITY_LABELS[value] || value,
      }));
      setPiiOptions(options);
      setSelectedPiiEntities(data.default_entities || []);
    } catch {
      // Non-critical - the checklist just won't be editable this session; the
      // backend still falls back to its own default entity list on upload.
    }
  }

  async function handleIngest(e) {
    e.preventDefault();
    if (!file) return;
    setIngesting(true);
    setIngestStatus(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("pii_entities", JSON.stringify(selectedPiiEntities));
      const { data } = await api.post("/ingest", form);
      setIngestStatus({ ok: true, message: `Ingested '${file.name}'.`, guardrails: data.guardrails });
      setFile(null);
      onIngested?.();
    } catch (err) {
      setIngestStatus({ ok: false, message: formatErrorDetail(err, "Ingestion failed.") });
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="traces-page">
      <div className="traces-page-header">
        <h1>Data Ingestion</h1>
        <p className="muted">Upload any document - PDF, XLSX, DOCX, or TXT. Only you can retrieve from what you upload.</p>
      </div>

      <div className="ingest-cards">
        <div className="ingest-card sidebar-section">
          <h3>Upload document</h3>
          <form onSubmit={handleIngest} className="sidebar-form">
            <input
              type="file"
              accept=".pdf,.xlsx,.docx,.txt"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />

            {piiOptions.length > 0 && (
              <div className="gr-field">
                <span className="field-label">PII to mask before storing</span>
                <div className="gr-checkboxes">
                  {piiOptions.map((opt) => (
                    <label key={opt.value} className="gr-checkbox-row">
                      <input
                        type="checkbox"
                        checked={selectedPiiEntities.includes(opt.value)}
                        disabled={ingesting}
                        onChange={(e) =>
                          setSelectedPiiEntities((prev) =>
                            e.target.checked ? [...prev, opt.value] : prev.filter((v) => v !== opt.value)
                          )
                        }
                      />
                      {opt.label}
                    </label>
                  ))}
                </div>
                <span className="gr-field-hint">
                  Unchecked types are stored as-is. This choice only applies to this upload.
                </span>
              </div>
            )}

            <button type="submit" className="btn-secondary btn-block" disabled={!file || ingesting}>
              {ingesting ? "Ingesting…" : "Ingest document"}
            </button>
          </form>
          {ingestStatus && (
            <p className={ingestStatus.ok ? "sidebar-status-ok" : "sidebar-status-error"}>{ingestStatus.message}</p>
          )}
          {ingestStatus?.guardrails && (
            <div className="sidebar-guardrails">
              {["file_type", "file_size"].map((key) => {
                const check = ingestStatus.guardrails[key];
                if (!check) return null;
                return (
                  <span key={key} className={`guardrail-badge ${check.passed ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
                    {check.passed ? "✓" : "✗"} {key.replace("_", " ")}
                  </span>
                );
              })}
              {(ingestStatus.guardrails.pii_masking?.pii_detected?.length || 0) > 0 &&
                ingestStatus.guardrails.pii_masking.pii_detected.map((p) => (
                  <span key={p.entity_type} className="guardrail-badge guardrail-badge-pii">
                    PII masked: {p.entity_type} {p.count > 1 ? `×${p.count}` : ""}
                  </span>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
