import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail, streamChat } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import DocumentsPanel from "../components/DocumentsPanel";
import ModelPicker from "../components/ModelPicker";
import ThemeToggle from "../components/ThemeToggle";
import ThinkingIndicator from "../components/ThinkingIndicator";
import { TracingTab } from "./Traces";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";
import { resolveBlockedGuardrailLabel } from "../data/guardrailChecklist";

const SECTIONS = [
  { id: "chat", label: "Chat", icon: "◧" },
  { id: "ingest", label: "Data Ingestion", icon: "▤" },
  { id: "documents", label: "Documents", icon: "▦" },
  { id: "tracing", label: "Tracing", icon: "≋" },
];

// Fallback cycling text only - shown before the first live stage arrives (or if
// polling never succeeds at all). Kept in the same order the real pipeline
// stages actually fire in, so the fallback and the live version read the same.
const THINKING_MESSAGES = [
  "Guardrails Agent: validating your question…",
  "Guardrails Agent: checking access & quota…",
  "Document Agent: classifying your question…",
  "Document Agent: searching your documents…",
  "Guardrails Agent: checking retrieval relevance…",
  "Document Agent: drafting an answer…",
  "Guardrails Agent: reviewing bias…",
  "Guardrails Agent: checking groundedness & output…",
];

// Human-readable labels for the entity type names GET /ingest/pii-options returns -
// same catalog as PII_ENTITY_OPTIONS on the Guardrails page, kept separate since
// this component doesn't import from Traces.jsx.
const SUGGESTED_PROMPTS = [
  "Summarize what's in this document",
  "What are the key numbers or figures mentioned?",
  "List any dates or deadlines referenced",
];

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
  const { user, logout, isAdmin } = useAuth();

  const [activeSection, setActiveSection] = useState("chat");

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [liveStage, setLiveStage] = useState("");
  const [openLogsIndex, setOpenLogsIndex] = useState(null);
  const [pendingTraceTurnId, setPendingTraceTurnId] = useState(null);

  const [file, setFile] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingesting, setIngesting] = useState(false);
  const [piiOptions, setPiiOptions] = useState([]);
  const [selectedPiiEntities, setSelectedPiiEntities] = useState([]);

  const [selectedModel, setSelectedModel] = useState("sonnet");

  const [hasDocuments, setHasDocuments] = useState(null); // null = not checked yet, so the banner never flashes

  const scrollRef = useRef(null);
  // Guards handleSend against double-submission (fast double-click/double-Enter
  // before the "sending" state re-render actually disables the button) - the
  // `sending` state alone isn't enough, since a second call can read the same
  // stale (pre-render) value from its closure. A ref updates synchronously, so
  // this closes that race window entirely.
  const sendingRef = useRef(false);

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
          turn_id: m.turn_id,
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

  function viewTrace(turnId) {
    setPendingTraceTurnId(turnId);
    setActiveSection("tracing");
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
    if (!question || sendingRef.current) return;
    sendingRef.current = true;

    // Every message this turn creates - the user's own question and the
    // streaming assistant reply - carries this same requestId in its id, so
    // later updates can find-and-replace the right one by identity instead of
    // assuming "whichever message is currently last in the array" is always
    // this turn's own placeholder. That assumption breaks if anything else
    // ever appends to messages while a stream is in flight - previously this
    // is exactly what let one turn's streamed text land inside another
    // message's bubble.
    const requestId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: `${requestId}-user`, role: "user", content: question }]);
    setInput("");
    setSending(true);
    setLiveStage("");

    // Polled while the request is in flight - GET /progress/{request_id} reports
    // whichever pipeline stage last ran (see app/core/progress.py), so the
    // "thinking" indicator reflects real backend progress instead of just
    // cycling a fixed list on a timer.
    const pollId = setInterval(async () => {
      try {
        const { data } = await api.get(`/progress/${requestId}`);
        if (data.stage) setLiveStage(data.stage);
      } catch {
        // Non-critical - the fallback cycling text just keeps showing.
      }
    }, 600);

    // Once the full answer is generated and has passed every guardrail
    // server-side, it's streamed back in small chunks purely for a typewriter
    // reveal - see app/core/streaming.py for why this isn't raw generation-time
    // token streaming. streamStarted flips the moment the first chunk arrives,
    // swapping the ThinkingIndicator for a growing assistant bubble.
    let streamStarted = false;
    const assistantId = `${requestId}-assistant`;

    try {
      const data = await streamChat(
        "/chat",
        { question, conversation_id: activeConversationId, model: selectedModel, request_id: requestId },
        {
          onDelta: (text) => {
            setMessages((prev) => {
              if (!streamStarted) {
                streamStarted = true;
                return [...prev, { id: assistantId, role: "assistant", content: text, streaming: true }];
              }
              return prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + text } : m));
            });
          },
        }
      );

      const finalMessage = {
        id: assistantId,
        role: "assistant",
        content: data.answer || "No answer received.",
        logs: data.logs,
        graph_response: data.graph_response,
        cached: data.graph_response?.guardrail_events?.some((ev) => ev.stage === "semantic_cache" && ev.cache_hit),
        response_time_ms: data.response_time_ms,
        turn_id: data.turn_id,
      };
      setMessages((prev) => {
        if (!streamStarted) return [...prev, finalMessage];
        return prev.map((m) => (m.id === assistantId ? finalMessage : m));
      });
      if (data.conversation_id && data.conversation_id !== activeConversationId) {
        setActiveConversationId(data.conversation_id);
      }
      loadConversations();
    } catch (err) {
      const errorMessage = { id: assistantId, role: "assistant", content: `Error: ${formatErrorDetail(err, "Failed to reach the backend.")}` };
      setMessages((prev) => {
        if (!streamStarted) return [...prev, errorMessage];
        return prev.map((m) => (m.id === assistantId ? errorMessage : m));
      });
    } finally {
      clearInterval(pollId);
      setLiveStage("");
      setSending(false);
      sendingRef.current = false;
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
      <div className="chat-nav-spacer" aria-hidden="true" />
      <aside className="chat-nav">
        <div className="chat-nav-top">
          <Link to="/" className="chat-nav-brand" title="Back to Projects">
            <span className="brand-mark">✦</span>
            <span className="chat-nav-label">AI Guardrails</span>
          </Link>
          <div className="chat-nav-top-actions">
            <ThemeToggle />
          </div>
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
              <span className="chat-nav-label">{s.label}</span>
            </button>
          ))}
        </nav>

        <div className="chat-nav-footer">
          <div className="chat-nav-account">
            <span className="chat-nav-avatar">{(user?.email || "?").charAt(0).toUpperCase()}</span>
            <span className="account-email chat-nav-label">{user?.email}</span>
          </div>
          <button className="btn-ghost chat-nav-logout" onClick={logout} title="Log out">
            <span className="chat-nav-icon">⎋</span>
            <span className="chat-nav-label">Log out</span>
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
                      <span className="chat-disclaimer-icon">◧</span>
                      <span>
                        You haven't ingested any documents yet — answers won't have anything to draw on. Upload one
                        from the <strong>Data Ingestion</strong> tab first.
                      </span>
                    </div>
                  )}

                  {messages.length === 0 && (
                    <div className="chat-welcome chat-welcome-document">
                      <span className="chat-welcome-eyebrow">Document chat</span>
                      <div className="chat-welcome-icon">▤</div>
                      <h2>Ask a question about your documents</h2>
                      <p className="chat-welcome-body">
                        Answers are grounded only in what you've ingested — every response runs through PII
                        masking, relevance, and groundedness checks before it reaches you.
                      </p>
                      {hasDocuments !== false && (
                        <div className="chat-welcome-prompts">
                          {SUGGESTED_PROMPTS.map((p) => (
                            <button
                              key={p}
                              type="button"
                              className="chat-welcome-prompt-chip"
                              onClick={() => setInput(p)}
                            >
                              {p}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {messages.map((msg, i) => (
                    <div key={msg.id || msg.turn_id || i} className={`chat-message chat-message-${msg.role}`}>
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
                      {msg.role === "assistant" && (() => {
                        const blockedLabel = resolveBlockedGuardrailLabel(msg.graph_response?.guardrail_events);
                        return blockedLabel && <span className="turn-blocked-badge">Blocked - {blockedLabel}</span>;
                      })()}
                      {isAdmin && msg.role === "assistant" && msg.turn_id && (
                        <button type="button" className="chat-logs-toggle" onClick={() => viewTrace(msg.turn_id)}>
                          View Trace
                        </button>
                      )}
                      {openLogsIndex === i && <GuardrailPanel logs={msg.logs} graphResponse={msg.graph_response} />}
                    </div>
                  ))}

                  {sending && !messages[messages.length - 1]?.streaming && (
                    <ThinkingIndicator messages={THINKING_MESSAGES} liveStage={liveStage} />
                  )}
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

        {activeSection === "tracing" && (
          <TracingTab
            projectId="ragchatbot"
            initialTurnId={pendingTraceTurnId}
            onConsumedInitialTurn={() => setPendingTraceTurnId(null)}
          />
        )}
      </main>
    </div>
  );
}
