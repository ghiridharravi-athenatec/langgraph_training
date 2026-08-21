import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail, streamChat } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import Modal from "../components/Modal";
import ModelPicker from "../components/ModelPicker";
import ThemeToggle from "../components/ThemeToggle";
import ThinkingIndicator from "../components/ThinkingIndicator";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";
import { SEARCH_ASK_GUARDRAIL_CHECKLIST } from "../data/guardrailChecklist";

// Fallback cycling text only - shown before the first live stage arrives (or if
// polling never succeeds at all). Kept in the same order the real pipeline
// stages actually fire in (see app/api/v1/search_ask.py), so the fallback and
// the live version read the same.
const THINKING_MESSAGES = [
  "Guardrails Agent: validating your question…",
  "Guardrails Agent: checking your quota…",
  "Search & Ask: drafting an answer…",
  "Guardrails Agent: checking the answer…",
];

const SUGGESTED_PROMPTS = [
  "Explain this concept in simple terms",
  "Give me a few ideas for...",
  "What's the difference between X and Y?",
];

export default function SearchAndAsk() {
  const { user, logout } = useAuth();

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [liveStage, setLiveStage] = useState("");
  const [openLogsIndex, setOpenLogsIndex] = useState(null);

  const [selectedModel, setSelectedModel] = useState("sonnet");

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const scrollRef = useRef(null);
  // See RagChatbot.jsx's identical comment - a ref closes the double-submit race a
  // plain "sending" state check can't (state updates aren't synchronous).
  const sendingRef = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    // Loads the sidebar's conversation list only - deliberately not selectFirst,
    // so opening this project always starts on a fresh "new chat" screen instead
    // of silently reopening whatever conversation was last active.
    loadConversations();
  }, []);

  async function loadConversations({ selectFirst = false } = {}) {
    setConversationsLoading(true);
    try {
      const { data } = await api.get("/search-ask/conversations");
      setConversations(data);
      if (selectFirst && data.length > 0) {
        await openConversation(data[0].id);
      }
    } catch {
      // Conversation history is a nice-to-have on top of the chat itself - a failure
      // here shouldn't block the user from starting a fresh conversation.
    } finally {
      setConversationsLoading(false);
    }
  }

  async function openConversation(conversationId) {
    setActiveConversationId(conversationId);
    setOpenLogsIndex(null);
    try {
      const { data } = await api.get(`/search-ask/conversations/${conversationId}/messages`);
      setMessages(
        data.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          logs: m.logs,
          guardrail_events: m.guardrail_events,
          blocked: m.blocked,
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

  async function deleteConversationById(e, conversationId) {
    e.stopPropagation();
    try {
      await api.delete(`/search-ask/conversations/${conversationId}`);
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

    // See RagChatbot.jsx's identical comment - every message this turn creates
    // carries this same requestId in its id, so streaming updates always find-and-
    // replace their own message rather than assuming "whichever is last".
    const requestId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: `${requestId}-user`, role: "user", content: question }]);
    setInput("");
    setSending(true);
    setLiveStage("");

    const pollId = setInterval(async () => {
      try {
        const { data } = await api.get(`/progress/${requestId}`);
        if (data.stage) setLiveStage(data.stage);
      } catch {
        // Non-critical - the fallback cycling text just keeps showing.
      }
    }, 600);

    let streamStarted = false;
    const assistantId = `${requestId}-assistant`;

    try {
      const data = await streamChat(
        "/search-ask/chat",
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
        guardrail_events: data.guardrail_events,
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

  async function loadDocuments() {
    setDocumentsLoading(true);
    try {
      const { data } = await api.get("/search-ask/documents");
      setDocuments(data);
    } catch {
      // Non-critical - the modal just shows an empty list until the next open.
    } finally {
      setDocumentsLoading(false);
    }
  }

  function openUploadModal() {
    setUploadStatus(null);
    setUploadModalOpen(true);
    loadDocuments();
  }

  async function handleUpload(e) {
    e.preventDefault();
    if (!uploadFile) return;
    setUploading(true);
    setUploadStatus(null);
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      await api.post("/search-ask/documents", form);
      setUploadStatus({ ok: true, message: `Uploaded '${uploadFile.name}'.` });
      setUploadFile(null);
      loadDocuments();
    } catch (err) {
      setUploadStatus({ ok: false, message: formatErrorDetail(err, "Upload failed.") });
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="chat-shell">
      <aside className="search-ask-nav">
        <div className="search-ask-nav-top">
          <Link to="/" className="search-ask-nav-brand" title="Back to Projects">
            <span className="brand-mark">✦</span>
            <span>Search & Ask</span>
          </Link>
          <ThemeToggle />
        </div>

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

        <div className="search-ask-nav-footer">
          <button type="button" className="btn-ghost search-ask-nav-footer-btn" onClick={openUploadModal}>
            <span aria-hidden="true">▤</span> Document ingestion
          </button>
          <div className="search-ask-nav-account">
            <span className="chat-nav-avatar">{(user?.email || "?").charAt(0).toUpperCase()}</span>
            <span className="account-email">{user?.email}</span>
          </div>
          <button type="button" className="btn-ghost search-ask-nav-footer-btn" onClick={logout}>
            <span aria-hidden="true">⎋</span> Log out
          </button>
        </div>
      </aside>

      <main className="chat-main">
        <div className="chat-scroll" ref={scrollRef}>
          <div className="chat-column">
            {messages.length === 0 && (
              <div className="chat-welcome chat-welcome-search">
                <span className="chat-welcome-eyebrow">General chat</span>
                <div className="chat-welcome-icon">◈</div>
                <h2>Ask me anything</h2>
                <p className="chat-welcome-body">
                  Answered from general knowledge, not grounded in any document - every question and
                  answer still runs through the same input/output guardrails as the rest of this app.
                </p>
                <div className="chat-welcome-prompts">
                  {SUGGESTED_PROMPTS.map((p) => (
                    <button key={p} type="button" className="chat-welcome-prompt-chip" onClick={() => setInput(p)}>
                      {p}
                    </button>
                  ))}
                </div>
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
                {msg.role === "assistant" && msg.response_time_ms != null && (
                  <span className="chat-response-time" title="Time to generate this answer">
                    {formatResponseTime(msg.response_time_ms)}
                  </span>
                )}
                {msg.role === "assistant" && (msg.logs?.length > 0 || msg.guardrail_events?.length > 0) && (
                  <button className="chat-logs-toggle" onClick={() => setOpenLogsIndex(openLogsIndex === i ? null : i)}>
                    {openLogsIndex === i ? "Hide guardrail checks" : "View guardrail checks"}
                  </button>
                )}
                {openLogsIndex === i && (
                  <GuardrailPanel logs={msg.logs} events={msg.guardrail_events} checklist={SEARCH_ASK_GUARDRAIL_CHECKLIST} />
                )}
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
              placeholder="Ask me anything…"
              disabled={sending}
            />
            <button type="submit" className="btn-primary" disabled={sending || !input.trim()}>
              Send
            </button>
          </div>
        </form>
      </main>

      <Modal open={uploadModalOpen} onClose={() => setUploadModalOpen(false)} title="Document ingestion">
        <p className="muted" style={{ marginTop: 0 }}>
          Upload a file to store it - it isn't extracted, chunked, or searchable in chat yet.
        </p>
        <form onSubmit={handleUpload} className="sidebar-form">
          <input type="file" accept=".pdf,.xlsx,.docx,.txt" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} />
          <button type="submit" className="btn-primary btn-block" disabled={!uploadFile || uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </form>
        {uploadStatus && (
          <p className={uploadStatus.ok ? "sidebar-status-ok" : "sidebar-status-error"}>{uploadStatus.message}</p>
        )}

        <div className="modal-document-list">
          <span className="field-label">Uploaded files</span>
          {documentsLoading && <p className="muted">Loading…</p>}
          {!documentsLoading && documents.length === 0 && <p className="muted">Nothing uploaded yet.</p>}
          {!documentsLoading &&
            documents.map((d) => (
              <div key={d.id} className="modal-document-item">
                <span className="modal-document-item-name">{d.filename}</span>
                <span className="modal-document-item-size">{(d.size_bytes / 1024).toFixed(1)} KB</span>
              </div>
            ))}
        </div>
      </Modal>
    </div>
  );
}
