import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import DocumentsPanel from "../components/DocumentsPanel";
import ModelPicker from "../components/ModelPicker";
import ThinkingIndicator from "../components/ThinkingIndicator";
import { TracingTab } from "./Traces";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";

const SECTIONS = [
  { id: "chat", label: "Chat", icon: "◧" },
  { id: "ingest", label: "Data Ingestion", icon: "▤" },
  { id: "documents", label: "Documents", icon: "▦" },
  { id: "tracing", label: "Tracing", icon: "≋" },
];

const THINKING_MESSAGES = [
  "Reading your question…",
  "Searching your documents…",
  "Reviewing relevant passages…",
  "Drafting an answer…",
  "Double-checking the response…",
];

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

export default function RagChatbot() {
  const { user, logout } = useAuth();

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeSection, setActiveSection] = useState("chat");

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [openLogsIndex, setOpenLogsIndex] = useState(null);

  const [file, setFile] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingesting, setIngesting] = useState(false);
  const [piiOptions, setPiiOptions] = useState([]);
  const [selectedPiiEntities, setSelectedPiiEntities] = useState([]);

  const [selectedModel, setSelectedModel] = useState("sonnet");

  const [hasDocuments, setHasDocuments] = useState(null); // null = not checked yet, so the banner never flashes

  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    loadConversations({ selectFirst: true });
    checkDocumentsStatus();
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

  async function checkDocumentsStatus() {
    try {
      const { data } = await api.get("/documents/status");
      setHasDocuments(data.has_documents);
    } catch {
      // Non-critical - worst case the disclaimer just doesn't show for this session.
    }
  }

  async function loadConversations({ selectFirst = false } = {}) {
    setConversationsLoading(true);
    try {
      const { data } = await api.get("/conversations");
      setConversations(data);
      if (selectFirst && data.length > 0) {
        await openConversation(data[0].id);
      }
    } catch {
      // Conversation history is a nice-to-have on top of the chat itself - a failure here
      // shouldn't block the user from starting a fresh conversation.
    } finally {
      setConversationsLoading(false);
    }
  }

  async function openConversation(conversationId) {
    setActiveConversationId(conversationId);
    setOpenLogsIndex(null);
    try {
      const { data } = await api.get(`/conversations/${conversationId}/messages`);
      setMessages(
        data.map((m) => ({
          role: m.role,
          content: m.content,
          logs: m.logs,
          graph_response: m.graph_response,
          cached: m.cached,
          response_time_ms: m.response_time_ms,
        }))
      );
    } catch {
      setMessages([]);
    }
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setOpenLogsIndex(null);
  }

  async function deleteConversationById(e, conversationId) {
    e.stopPropagation();
    try {
      await api.delete(`/conversations/${conversationId}`);
      if (conversationId === activeConversationId) {
        startNewChat();
      }
      await loadConversations();
    } catch {
      // Non-critical - the list will just be stale until the next successful refresh.
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    const question = input.trim();
    if (!question || sending) return;

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setSending(true);

    try {
      const { data } = await api.post("/chat", { question, conversation_id: activeConversationId, model: selectedModel });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "No answer received.",
          logs: data.logs,
          graph_response: data.graph_response,
          cached: data.graph_response?.guardrail_events?.some((ev) => ev.stage === "semantic_cache" && ev.cache_hit),
          response_time_ms: data.response_time_ms,
        },
      ]);
      if (data.conversation_id && data.conversation_id !== activeConversationId) {
        setActiveConversationId(data.conversation_id);
      }
      loadConversations();
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${formatErrorDetail(err, "Failed to reach the backend.")}` },
      ]);
    } finally {
      setSending(false);
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
      checkDocumentsStatus();
    } catch (err) {
      setIngestStatus({ ok: false, message: formatErrorDetail(err, "Ingestion failed.") });
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="chat-shell">
      <aside className={`chat-nav ${sidebarOpen ? "" : "chat-nav-collapsed"}`}>
        <div className="chat-nav-top">
          <Link to="/" className="chat-nav-brand" title="Back to Projects">
            <span className="brand-mark">✦</span>
            {sidebarOpen && <span>AI Assistance</span>}
          </Link>
          <button
            type="button"
            className="chat-nav-toggle"
            onClick={() => setSidebarOpen((v) => !v)}
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? "‹" : "›"}
          </button>
        </div>

        <nav className="chat-nav-list">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`chat-nav-item ${activeSection === s.id ? "chat-nav-item-active" : ""}`}
              onClick={() => setActiveSection(s.id)}
              title={s.label}
            >
              <span className="chat-nav-icon">{s.icon}</span>
              {sidebarOpen && <span>{s.label}</span>}
            </button>
          ))}
        </nav>

        <div className="chat-nav-footer">
          {sidebarOpen && <span className="account-email">{user?.email}</span>}
          <button className="btn-ghost" onClick={logout} title="Log out">
            {sidebarOpen ? "Log out" : "⎋"}
          </button>
        </div>
      </aside>

      <main className="chat-nav-main">
        {activeSection === "chat" && (
          <div className="chat-section animate-switch">
            <aside className="chat-conversations-rail">
              <button className="btn-new-chat" onClick={startNewChat}>
                <span>+</span> New chat
              </button>

              <div className="conversation-list">
                {conversationsLoading && <p className="muted conversation-list-empty">Loading…</p>}
                {!conversationsLoading && conversations.length === 0 && (
                  <p className="muted conversation-list-empty">No conversations yet</p>
                )}
                {conversations.map((c) => (
                  <div
                    key={c.id}
                    className={`conversation-item ${c.id === activeConversationId ? "conversation-item-active" : ""}`}
                    onClick={() => openConversation(c.id)}
                  >
                    <span className="conversation-item-title">{c.title}</span>
                    <button
                      className="conversation-item-delete"
                      title="Delete conversation"
                      onClick={(e) => deleteConversationById(e, c.id)}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </aside>

            <div className="chat-main">
              <div className="chat-scroll" ref={scrollRef}>
                <div className="chat-column">
                  {hasDocuments === false && (
                    <div className="chat-disclaimer">
                      You haven't ingested any documents yet — answers won't have anything to draw on. Upload one
                      from the <strong>Data Ingestion</strong> tab first.
                    </div>
                  )}

                  {messages.length === 0 && (
                    <div className="chat-empty">
                      <div className="chat-empty-mark">✦</div>
                      <h2>Ask a question about your documents</h2>
                      <p className="muted">Answers are grounded in the documents you've ingested.</p>
                    </div>
                  )}

                  {messages.map((msg, i) => (
                    <div key={i} className={`chat-message chat-message-${msg.role}`}>
                      <div className="chat-bubble">
                        {msg.role === "assistant" ? (
                          <div className="markdown-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatPiiTokens(msg.content)}</ReactMarkdown>
                          </div>
                        ) : (
                          <p>{msg.content}</p>
                        )}
                      </div>
                      {/* {msg.role === "assistant" && msg.cached && (
                        <span className="cache-indicator">↺ Reused from a similar question</span>
                      )}
                      {(msg.logs?.length || msg.graph_response) && (
                        <button className="chat-logs-toggle" onClick={() => setOpenLogsIndex(openLogsIndex === i ? null : i)}>
                          {openLogsIndex === i ? "Hide logs" : "View logs"}
                        </button>
                      )} */}
                      {msg.role === "assistant" && msg.response_time_ms != null && (
                        <span className="chat-response-time" title="Time to generate this answer">
                          {formatResponseTime(msg.response_time_ms)}
                        </span>
                      )}
                      {openLogsIndex === i && <GuardrailPanel logs={msg.logs} graphResponse={msg.graph_response} />}
                    </div>
                  ))}

                  {sending && <ThinkingIndicator messages={THINKING_MESSAGES} />}
                </div>
              </div>

              <form onSubmit={handleSend} className="chat-input-bar">
                <div className="chat-input-toolbar">
                  <ModelPicker value={selectedModel} onChange={setSelectedModel} disabled={sending} />
                </div>
                <div className="chat-input-column">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder={
                      hasDocuments === false
                        ? "Ingest a document before you can ask a question…"
                        : "Ask a question about your documents…"
                    }
                    disabled={sending || hasDocuments === false}
                  />
                  <button type="submit" className="btn-primary" disabled={sending || hasDocuments === false || !input.trim()}>
                    Send
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {activeSection === "ingest" && (
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
        )}

        {activeSection === "documents" && <DocumentsPanel />}

        {activeSection === "tracing" && <TracingTab projectId="ragchatbot" />}
      </main>
    </div>
  );
}
