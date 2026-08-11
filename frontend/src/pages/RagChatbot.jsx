import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import { useAuth } from "../context/AuthContext";

const COLLECTIONS = ["warranty", "user_manual", "inspection_report"];

export default function RagChatbot() {
  const { user, logout } = useAuth();

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [openLogsIndex, setOpenLogsIndex] = useState(null);

  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [ingestCollection, setIngestCollection] = useState(COLLECTIONS[0]);
  const [file, setFile] = useState(null);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingesting, setIngesting] = useState(false);

  const [manageCollection, setManageCollection] = useState(COLLECTIONS[0]);
  const [manageStatus, setManageStatus] = useState(null);
  const [managing, setManaging] = useState(false);

  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    loadConversations({ selectFirst: true });
  }, []);

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
      const { data } = await api.post("/chat", { question, conversation_id: activeConversationId });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "No answer received.",
          logs: data.logs,
          graph_response: data.graph_response,
          cached: data.graph_response?.guardrail_events?.some((ev) => ev.stage === "semantic_cache" && ev.cache_hit),
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
      const { data } = await api.post("/ingest", form, { params: { collection_name: ingestCollection } });
      setIngestStatus({ ok: true, message: `Ingested into '${ingestCollection}'.`, guardrails: data.guardrails });
      setFile(null);
    } catch (err) {
      setIngestStatus({ ok: false, message: formatErrorDetail(err, "Ingestion failed.") });
    } finally {
      setIngesting(false);
    }
  }

  async function handleClear() {
    setManaging(true);
    setManageStatus(null);
    try {
      const { data } = await api.delete(`/clear/${manageCollection}`);
      setManageStatus({ ok: true, message: data.message || "Cleared." });
    } catch (err) {
      setManageStatus({ ok: false, message: formatErrorDetail(err, "Failed to clear.") });
    } finally {
      setManaging(false);
    }
  }

  async function handleDelete() {
    setManaging(true);
    setManageStatus(null);
    try {
      const { data } = await api.delete(`/delete/${manageCollection}`);
      setManageStatus({ ok: true, message: data.message || "Deleted." });
    } catch (err) {
      setManageStatus({ ok: false, message: formatErrorDetail(err, "Failed to delete.") });
    } finally {
      setManaging(false);
    }
  }

  return (
    <div className="chat-shell">
      <aside className="chat-sidebar">
        <Link to="/" className="brand brand-sidebar">
          <span className="brand-mark">✦</span>
          <span>AI Assistance</span>
        </Link>

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

        <div className="sidebar-accordion">
          <button className="sidebar-accordion-toggle" onClick={() => setDocumentsOpen((v) => !v)}>
            <span>Documents</span>
            <span className={`accordion-chevron ${documentsOpen ? "accordion-chevron-open" : ""}`}>▾</span>
          </button>

          {documentsOpen && (
            <div className="sidebar-accordion-body">
              <div className="sidebar-section">
                <h3>Upload document</h3>
                <label className="field">
                  <span className="field-label">Collection</span>
                  <select value={ingestCollection} onChange={(e) => setIngestCollection(e.target.value)}>
                    {COLLECTIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </label>
                <form onSubmit={handleIngest} className="sidebar-form">
                  <input
                    type="file"
                    accept=".pdf,.xlsx"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
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

              <div className="sidebar-section">
                <h3>Manage collections</h3>
                <label className="field">
                  <span className="field-label">Collection</span>
                  <select value={manageCollection} onChange={(e) => setManageCollection(e.target.value)}>
                    {COLLECTIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="sidebar-form-row">
                  <button className="btn-secondary" onClick={handleClear} disabled={managing}>
                    Clear
                  </button>
                  <button className="btn-danger" onClick={handleDelete} disabled={managing}>
                    Delete
                  </button>
                </div>
                {manageStatus && (
                  <p className={manageStatus.ok ? "sidebar-status-ok" : "sidebar-status-error"}>{manageStatus.message}</p>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <span className="account-email">{user?.email}</span>
          <button className="btn-ghost" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>

      <main className="chat-main">
        <header className="chat-topbar">
          <h1>RAG Chatbot</h1>
        </header>

        <div className="chat-scroll" ref={scrollRef}>
          <div className="chat-column">
            {messages.length === 0 && (
              <div className="chat-empty">
                <div className="chat-empty-mark">✦</div>
                <h2>Ask a question about your documents</h2>
                <p className="muted">Answers are grounded in warranty, user manual, and inspection report content.</p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`chat-message chat-message-${msg.role}`}>
                <div className="chat-bubble">
                  {msg.role === "assistant" ? (
                    <div className="markdown-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <p>{msg.content}</p>
                  )}
                </div>
                {msg.role === "assistant" && msg.cached && (
                  <span className="cache-indicator">↺ Reused from a similar question</span>
                )}
                {(msg.logs?.length || msg.graph_response) && (
                  <button className="chat-logs-toggle" onClick={() => setOpenLogsIndex(openLogsIndex === i ? null : i)}>
                    {openLogsIndex === i ? "Hide logs" : "View logs"}
                  </button>
                )}
                {openLogsIndex === i && <GuardrailPanel logs={msg.logs} graphResponse={msg.graph_response} />}
              </div>
            ))}

            {sending && (
              <div className="chat-message chat-message-assistant">
                <div className="chat-bubble chat-bubble-typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}
          </div>
        </div>

        <form onSubmit={handleSend} className="chat-input-bar">
          <div className="chat-input-column">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents…"
              disabled={sending}
            />
            <button type="submit" className="btn-primary" disabled={sending || !input.trim()}>
              Send
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
