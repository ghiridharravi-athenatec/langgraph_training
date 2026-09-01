import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail, streamChat } from "../api/client";
import GuardrailPanel from "../components/GuardrailPanel";
import DocumentsPanel from "../components/DocumentsPanel";
import IngestPanel from "../components/IngestPanel";
import DatabaseIngestPanel from "../components/DatabaseIngestPanel";
import CopyButton from "../components/CopyButton";
import ModelPicker from "../components/ModelPicker";
import ThemeToggle from "../components/ThemeToggle";
import ThinkingIndicator from "../components/ThinkingIndicator";
import { TracingTab } from "./Traces";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";
import { resolveBlockedGuardrailLabel } from "../data/guardrailChecklist";

// Fallback cycling text only - shown before the first live stage arrives (or if
// polling never succeeds at all). Kept in the same order the real pipeline
// stages actually fire in, so the fallback and the live version read the same.
const THINKING_MESSAGES = [
  "Guardrails: validating your question…",
  "Guardrails: checking your quota…",
  "Supervisor Agent: deciding how to answer…",
  "Supervisor Agent: picked Sonnet for this question…",
  "Document Agent: classifying your question…",
  "Document Agent: searching your documents…",
  "Guardrails: checking retrieval relevance…",
  "Document Agent: drafting an answer…",
  "Guardrails: reviewing bias…",
  "Guardrails: checking groundedness & output…",
  "Document Agent: trying a different search…",
  "Document Agent: searching your documents again…",
];

const SUGGESTED_PROMPTS = [
  "Summarize what's in this document",
  "What are the key numbers or figures mentioned?",
  "List any dates or deadlines referenced",
];

// Which project grant unlocks the Database Connections section - same grant
// app/core/orchestrator.py's filter_routes_by_permission already requires before it
// will route a chat turn to database_chat, so this only mirrors an access requirement
// that already exists rather than introducing a new one.
const DATABASE_SECTION_PROJECT_ID = "database-chatbot";

// Human-readable labels for the route names app/core/orchestrator.py's ALL_ROUTES
// produces - shown as a small badge on each answer so the Supervisor's routing
// decision is visible, not a hidden implementation detail.
const ROUTE_LABELS = {
  document_chat: "Answered from your documents",
  database_chat: "Answered from your database",
  both: "Answered from your documents & database",
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

  const [selectedModel, setSelectedModel] = useState("auto");

  const [hasDocuments, setHasDocuments] = useState(null); // null = not checked yet, so the banner never flashes
  const [projectIds, setProjectIds] = useState([]);
  const [hasConnections, setHasConnections] = useState(null);

  const canManageConnections = projectIds.includes(DATABASE_SECTION_PROJECT_ID);
  // Combined "has anything grounded to answer from" - mirrors the exact same
  // has_documents/database_chat availability check _generate_chat_response
  // (app/api/v1/api.py) runs before the Supervisor ever gets to decide.
  const hasAnySource = hasDocuments === null && hasConnections === null
    ? null
    : Boolean(hasDocuments) || Boolean(canManageConnections && hasConnections);
  const sections = [
    { id: "chat", label: "Chat", icon: "◧" },
    { id: "ingest", label: "Data Ingestion", icon: "▤" },
    { id: "documents", label: "Documents", icon: "▦" },
    canManageConnections && { id: "connections", label: "Database Connections", icon: "⛁" },
    { id: "tracing", label: "Tracing", icon: "≋" },
  ].filter(Boolean);

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
    // Loads the sidebar's conversation list only - deliberately not selectFirst,
    // so opening this project always starts on a fresh "new chat" screen instead
    // of silently reopening whatever conversation was last active.
    loadConversations();
    checkDocumentsStatus();
    loadProjects();
  }, []);

  useEffect(() => {
    // Only fetch connection status once we know the user actually holds the
    // database-chatbot grant - otherwise GET /database/connections just 403s.
    if (canManageConnections) loadConnections();
  }, [canManageConnections]);

  async function checkDocumentsStatus() {
    try {
      const { data } = await api.get("/documents/status");
      setHasDocuments(data.has_documents);
    } catch {
      // Non-critical - worst case the disclaimer just doesn't show for this session.
    }
  }

  async function loadProjects() {
    try {
      const { data } = await api.get("/projects");
      setProjectIds(data.map((p) => p.id));
    } catch {
      // Non-critical - the Database Connections section just won't show for this
      // session; Chat/Data Ingestion/Documents/Tracing are unaffected.
    }
  }

  async function loadConnections() {
    try {
      const { data } = await api.get("/database/connections");
      handleConnectionsChanged(data);
    } catch {
      // Non-critical - worst case the disclaimer just doesn't show for this session.
    }
  }

  function handleConnectionsChanged(data) {
    setHasConnections(data.length > 0);
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
          guardrail_events: m.guardrail_events,
          cached: m.cached,
          response_time_ms: m.response_time_ms,
          turn_id: m.turn_id,
          routed_to: m.routed_to,
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
        guardrail_events: data.guardrail_events,
        cached: data.graph_response?.guardrail_events?.some((ev) => ev.stage === "semantic_cache" && ev.cache_hit),
        response_time_ms: data.response_time_ms,
        turn_id: data.turn_id,
        routed_to: data.routed_to,
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
          {sections.map((s) => (
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
                  {hasAnySource === false && (
                    <div className="chat-disclaimer">
                      <span className="chat-disclaimer-icon">◧</span>
                      <span>
                        You haven't ingested any documents{canManageConnections ? " or connected a database" : ""} yet
                        — answers won't have anything to draw on. Upload one from the <strong>Data Ingestion</strong> tab
                        {canManageConnections ? (
                          <>
                            {" "}or connect one from the <strong>Database Connections</strong> tab
                          </>
                        ) : null} first.
                      </span>
                    </div>
                  )}

                  {messages.length === 0 && (
                    <div className="chat-welcome chat-welcome-document">
                      <span className="chat-welcome-eyebrow">Conversational Intelligence</span>
                      <div className="chat-welcome-icon">▤</div>
                      <h2>Ask a question about your documents or database</h2>
                      <p className="chat-welcome-body">
                        A Supervisor decides which grounded source actually answers - only your own documents or
                        connected database, never the model's own general knowledge. Every response still runs
                        through PII masking, relevance, and groundedness checks before it reaches you.
                      </p>
                      {hasAnySource !== false && (
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
                      {msg.role === "user" && <CopyButton text={msg.content} label="Copy question" />}
                      {/* {msg.role === "assistant" && msg.cached && (
                        <span className="cache-indicator">↺ Reused from a similar question</span>
                      )}
                      {(msg.logs?.length || msg.graph_response) && (
                        <button className="chat-logs-toggle" onClick={() => setOpenLogsIndex(openLogsIndex === i ? null : i)}>
                          {openLogsIndex === i ? "Hide logs" : "View logs"}
                        </button>
                      )} */}
                      {msg.role === "assistant" && msg.routed_to && (
                        <span className="chat-response-time" title="Which source the Supervisor routed this question to">
                          {ROUTE_LABELS[msg.routed_to] || msg.routed_to}
                        </span>
                      )}
                      {msg.role === "assistant" && msg.response_time_ms != null && (
                        <span className="chat-response-time" title="Time to generate this answer">
                          {formatResponseTime(msg.response_time_ms)}
                        </span>
                      )}
                      {msg.role === "assistant" && (() => {
                        const blockedLabel = resolveBlockedGuardrailLabel(msg.graph_response?.guardrail_events || msg.guardrail_events);
                        return blockedLabel && <span className="turn-blocked-badge">Blocked - {blockedLabel}</span>;
                      })()}
                      {isAdmin && msg.role === "assistant" && msg.turn_id && (
                        <button type="button" className="chat-logs-toggle" onClick={() => viewTrace(msg.turn_id)}>
                          View Trace
                        </button>
                      )}
                      {msg.role === "assistant" && !msg.streaming && (
                        <CopyButton text={formatPiiTokens(msg.content)} />
                      )}
                      {openLogsIndex === i && (
                        <GuardrailPanel logs={msg.logs} graphResponse={msg.graph_response} events={msg.guardrail_events} />
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
                    placeholder={
                      hasAnySource === false
                        ? "Ingest a document or connect a database before you can ask a question…"
                        : "Ask a question about your documents or database…"
                    }
                    disabled={sending || hasAnySource === false}
                  />
                  <button type="submit" className="btn-primary" disabled={sending || hasAnySource === false || !input.trim()}>
                    Send
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {activeSection === "ingest" && <IngestPanel onIngested={checkDocumentsStatus} />}

        {activeSection === "documents" && <DocumentsPanel />}

        {activeSection === "connections" && canManageConnections && (
          <div className="traces-page">
            <div className="traces-page-header">
              <h1>Database Connections</h1>
              <p className="muted">Connect an external database - read-only, only you can query what you connect.</p>
            </div>
            <DatabaseIngestPanel onConnectionsChanged={handleConnectionsChanged} />
          </div>
        )}

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
