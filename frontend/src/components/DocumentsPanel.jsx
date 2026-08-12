import { useEffect, useState } from "react";
import api, { formatErrorDetail } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { formatPiiTokens } from "../utils/formatPii";

function formatDate(value) {
  return new Date(value).toLocaleString();
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DocumentDetail({ document, onBack }) {
  return (
    <div>
      <button type="button" className="trace-breadcrumb-link document-back" onClick={onBack}>
        ← Back to documents
      </button>

      <div className="traces-page-header">
        <h1>{document.filename}</h1>
        <p className="muted">
          {document.content_type.toUpperCase()} · {formatSize(document.size_bytes)} · {document.chunk_count} chunk
          {document.chunk_count === 1 ? "" : "s"} · Uploaded {formatDate(document.created_at)}
          {document.uploaded_by ? ` by ${document.uploaded_by}` : ""}
        </p>
      </div>

      <div className="document-viewer">
        <div className="document-viewer-label">
          <span>Extracted content</span>
          <span className="guardrail-badge guardrail-badge-pii">PII masked</span>
        </div>
        <textarea className="document-viewer-textarea" value={formatPiiTokens(document.extracted_text)} readOnly />
      </div>
    </div>
  );
}

export default function DocumentsPanel() {
  const { isAdmin } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  const [selectedId, setSelectedId] = useState(null);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [detailStatus, setDetailStatus] = useState("idle");

  useEffect(() => {
    api
      .get("/documents")
      .then(({ data }) => {
        setDocuments(data);
        setStatus("ready");
      })
      .catch((err) => {
        setError(formatErrorDetail(err, "Failed to load documents."));
        setStatus("error");
      });
  }, []);

  async function openDocument(id) {
    setSelectedId(id);
    setDetailStatus("loading");
    try {
      const { data } = await api.get(`/documents/${id}`);
      setSelectedDocument(data);
      setDetailStatus("ready");
    } catch (err) {
      setError(formatErrorDetail(err, "Failed to load this document."));
      setDetailStatus("error");
    }
  }

  function closeDocument() {
    setSelectedId(null);
    setSelectedDocument(null);
  }

  if (selectedId) {
    return (
      <div className="traces-page">
        {detailStatus === "loading" && <p className="muted">Loading…</p>}
        {detailStatus === "error" && <p className="form-error">{error}</p>}
        {detailStatus === "ready" && selectedDocument && (
          <DocumentDetail document={selectedDocument} onBack={closeDocument} />
        )}
      </div>
    );
  }

  return (
    <div className="traces-page">
      <div className="traces-page-header">
        <h1>Documents</h1>
        <p className="muted">
          {isAdmin ? "Every document ingested, across every user." : "Documents you've ingested."} Click one to view
          its extracted content.
        </p>
      </div>

      {status === "loading" && <p className="muted">Loading…</p>}
      {status === "error" && <p className="form-error">{error}</p>}

      {status === "ready" && documents.length === 0 && (
        <div className="empty-state">
          <p>No documents ingested yet.</p>
        </div>
      )}

      {status === "ready" && documents.length > 0 && (
        <div className="table-scroll">
          <table className="permission-table trace-turn-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Size</th>
                <th>Chunks</th>
                {isAdmin && <th>Uploaded by</th>}
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.id} className="trace-turn-row" onClick={() => openDocument(d.id)}>
                  <td className="trace-turn-question">{d.filename}</td>
                  <td>
                    <span className="guardrail-badge">{d.content_type}</span>
                  </td>
                  <td className="trace-turn-time">{formatSize(d.size_bytes)}</td>
                  <td className="trace-turn-time">{d.chunk_count}</td>
                  {isAdmin && <td>{d.uploaded_by || "—"}</td>}
                  <td className="trace-turn-time">{formatDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
