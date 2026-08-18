import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api, { formatErrorDetail, streamChat } from "../api/client";
import DatabaseIngestPanel from "../components/DatabaseIngestPanel";
import ModelPicker from "../components/ModelPicker";
import ThemeToggle from "../components/ThemeToggle";
import ThinkingIndicator from "../components/ThinkingIndicator";
import ToolCallLog from "../components/ToolCallLog";
import { TracingTab } from "./Traces";
import { useAuth } from "../context/AuthContext";
import { formatResponseTime } from "../utils/formatResponseTime";
import { formatPiiTokens } from "../utils/formatPii";

const SECTIONS = [
  { id: "chat", label: "Chat", icon: "◧" },
  { id: "connections", label: "Connections", icon: "▤" },
  { id: "tracing", label: "Tracing", icon: "≋" },
];

// Fallback cycling text only - shown before the first live stage arrives (or if
// polling never succeeds at all). Kept in the same order the real pipeline
// stages actually fire in, so the fallback and the live version read the same.
const THINKING_MESSAGES = [
  "Guardrails Agent: validating your question…",
  "Guardrails Agent: checking your quota…",
  "Database Agent: inspecting the database…",
  "Database Agent: running a query…",
  "Database Agent: reviewing the results…",
  "Guardrails Agent: checking the answer…",
];

const SUGGESTED_PROMPTS = [
  "What tables are available in this database?",
  "How many rows are in the largest table?",
  "Show me a sample of the first table",
];

export default function DatabaseChatbot() {
  const { user, logout, isAdmin } = useAuth();

  const [activeSection, setActiveSection] = useState("chat");

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [conversationsLoading, setConversationsLoading] = useState(true);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [liveStage, setLiveStage] = useState("");
  const [pendingTraceTurnId, setPendingTraceTurnId] = useState(null);

  const [connections, setConnections] = useState([]);
  const [hasConnections, setHasConnections] = useState(null); // null = not checked yet, so the banner never flashes
  const [selectedConnectionId, setSelectedConnectionId] = useState("");
  const [selectedModel, setSelectedModel] = useState("sonnet");

  // True when the open conversation is pinned to a connection that's since been
  // deleted - the input gets disabled instead of letting the user hit a confusing
  // 404 after Send. activeConversation is undefined for a brand-new chat, so this
  // is always false there.
  const activeConversation = conversations.find((c) => c.id === activeConversationId);
  const activeConnectionMissing =
    !!activeConversation?.connection_id && !connections.some((c) => c.id === activeConversation.connection_id);

  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    loadConversations({ selectFirst: true });
    loadConnections();
  }, []);

  async function loadConnections() {
    try {
      const { data } = await api.get("/database/connections");
      handleConnectionsChanged(data);
    } catch {
      // Non-critical - worst case the disclaimer just doesn't show for this session.
    }
  }

  function handleConnectionsChanged(data) {
    setConnections(data);
    setHasConnections(data.length > 0);
    // Only auto-adjust the picker outside an active conversation - once a
    // conversation has turns it's pinned server-side, so the picker shouldn't
    // silently jump to a different value underneath a disabled control.
    if (messages.length === 0) {
      setSelectedConnectionId((prev) => (prev && data.some((c) => c.id === prev) ? prev : data[0]?.id || ""));
    }
  }

  async function loadConversations({ selectFirst = false } = {}) {
    setConversationsLoading(true);
    try {
      const { data } = await api.get("/database/conversations");
      setConversations(data);
      if (selectFirst && data.length > 0) {
        await openConversation(data[0]);
      }
    } catch {
      // Conversation history is a nice-to-have on top of the chat itself - a failure here
      // shouldn't block the user from starting a fresh conversation.
    } finally {
      setConversationsLoading(false);
    }
  }

  async function openConversation(conversation) {
    setActiveConversationId(conversation.id);
    if (conversation.connection_id) setSelectedConnectionId(conversation.connection_id);
    try {
      const { data } = await api.get(`/database/conversations/${conversation.id}/messages`);
      setMessages(
        data.map((m) => ({
          role: m.role,
          content: m.content,
          response_time_ms: m.response_time_ms,
          guardrail_events: m.guardrail_events,
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
    // Re-validate against currently loaded connections - openConversation may have
    // left this pointed at a connection that's since been deleted (see
    // activeConnectionMissing), and unlike handleConnectionsChanged this wasn't
    // re-checked just because the conversation changed.
    setSelectedConnectionId((prev) => (prev && connections.some((c) => c.id === prev) ? prev : connections[0]?.id || ""));
  }

  function viewTrace(turnId) {
    setPendingTraceTurnId(turnId);
    setActiveSection("tracing");
  }

  async function deleteConversationById(e, conversationId) {
    e.stopPropagation();
    try {
      await api.delete(`/database/conversations/${conversationId}`);
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
    if (!question || sending || !selectedConnectionId || activeConnectionMissing) return;

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setSending(true);
    setLiveStage("");

    // Polled while the request is in flight - GET /progress/{request_id} reports
    // whichever pipeline/agent stage last ran (see app/core/progress.py), so the
    // "thinking" indicator reflects real backend progress instead of just
    // cycling a fixed list on a timer.
    const requestId = crypto.randomUUID();
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

    try {
      const data = await streamChat(
        "/database/chat",
        {
          question,
          conversation_id: activeConversationId,
          connection_id: selectedConnectionId,
          model: selectedModel,
          request_id: requestId,
        },
        {
          onDelta: (text) => {
            setMessages((prev) => {
              if (!streamStarted) {
                streamStarted = true;
                return [...prev, { role: "assistant", content: text, streaming: true }];
              }
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + text };
              return next;
            });
          },
        }
      );

      const finalMessage = {
        role: "assistant",
        content: data.answer || "No answer received.",
        response_time_ms: data.response_time_ms,
        guardrail_events: data.guardrail_events,
        turn_id: data.turn_id,
      };
      setMessages((prev) => {
        if (!streamStarted) return [...prev, finalMessage];
        const next = [...prev];
        next[next.length - 1] = finalMessage;
        return next;
      });
      if (data.conversation_id && data.conversation_id !== activeConversationId) {
        setActiveConversationId(data.conversation_id);
      }
      loadConversations();
    } catch (err) {
      const errorMessage = { role: "assistant", content: `Error: ${formatErrorDetail(err, "Failed to reach the backend.")}` };
      setMessages((prev) => {
        if (!streamStarted) return [...prev, errorMessage];
        const next = [...prev];
        next[next.length - 1] = errorMessage;
        return next;
      });
    } finally {
      clearInterval(pollId);
      setLiveStage("");
      setSending(false);
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
                    onClick={() => openConversation(c)}
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
                  {hasConnections === false && (
                    <div className="chat-disclaimer">
                      <span className="chat-disclaimer-icon">⛁</span>
                      <span>
                        You haven't connected a database yet — answers won't have anything to draw on. Connect one
                        from the <strong>Connections</strong> tab first.
                      </span>
                    </div>
                  )}

                  {activeConnectionMissing && (
                    <div className="chat-disclaimer">
                      <span className="chat-disclaimer-icon">⛁</span>
                      <span>
                        This conversation's database connection has been removed — you can still read the history
                        below, but can't ask anything new here. Start a <strong>New chat</strong> and pick an active
                        connection instead.
                      </span>
                    </div>
                  )}

                  {messages.length === 0 && (
                    <div className="chat-welcome chat-welcome-database">
                      <span className="chat-welcome-eyebrow">Database chat</span>
                      <div className="chat-welcome-icon">⛁</div>
                      <h2>Ask a question about a connected database</h2>
                      <p className="chat-welcome-body">
                        Answers come from a live, read-only query — the agent inspects your schema, writes a
                        query, and validates the result before it ever reaches you.
                      </p>
                      {hasConnections !== false && !activeConnectionMissing && (
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
                      {msg.role === "assistant" && msg.response_time_ms != null && (
                        <span className="chat-response-time" title="Time to generate this answer">
                          {formatResponseTime(msg.response_time_ms)}
                        </span>
                      )}
                      {isAdmin && msg.role === "assistant" && msg.turn_id && (
                        <button type="button" className="chat-logs-toggle" onClick={() => viewTrace(msg.turn_id)}>
                          View Trace
                        </button>
                      )}
                      {msg.role === "assistant" && <ToolCallLog events={msg.guardrail_events} />}
                    </div>
                  ))}

                  {sending && !messages[messages.length - 1]?.streaming && (
                    <ThinkingIndicator messages={THINKING_MESSAGES} liveStage={liveStage} />
                  )}
                </div>
              </div>

              <form onSubmit={handleSend} className="chat-input-bar">
                <div className="chat-input-toolbar">
                  <div className="model-picker">
                    <span className="model-picker-icon">⛁</span>
                    <select
                      value={selectedConnectionId}
                      onChange={(e) => setSelectedConnectionId(e.target.value)}
                      disabled={sending || messages.length > 0 || connections.length === 0}
                      title={messages.length > 0 ? "A conversation stays on the database it started with" : undefined}
                    >
                      {connections.length === 0 && <option value="">No databases connected</option>}
                      {connections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({c.engine})
                        </option>
                      ))}
                    </select>
                  </div>
                  <ModelPicker value={selectedModel} onChange={setSelectedModel} disabled={sending} />
                </div>
                <div className="chat-input-column">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder={
                      activeConnectionMissing
                        ? "This conversation's database connection was removed…"
                        : hasConnections === false
                        ? "Connect a database before you can ask a question…"
                        : "Ask a question about the selected database…"
                    }
                    disabled={sending || !selectedConnectionId || activeConnectionMissing}
                  />
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={sending || !selectedConnectionId || !input.trim() || activeConnectionMissing}
                  >
                    Send
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {activeSection === "connections" && (
          <div className="traces-page">
            <div className="traces-page-header">
              <h1>Connections</h1>
              <p className="muted">
                Connect an external database - read-only, only you can query what you connect.
              </p>
            </div>
            <DatabaseIngestPanel onConnectionsChanged={handleConnectionsChanged} />
          </div>
        )}

        {activeSection === "tracing" && (
          <TracingTab
            projectId="database-chatbot"
            initialTurnId={pendingTraceTurnId}
            onConsumedInitialTurn={() => setPendingTraceTurnId(null)}
          />
        )}
      </main>
    </div>
  );
}
