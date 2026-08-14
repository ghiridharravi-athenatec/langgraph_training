import AppShell from "../components/AppShell";

function FlowBar({ steps }) {
  return (
    <div className="instructions-flow">
      {steps.map((step, i) => (
        <span key={step} className="instructions-flow-step">
          {step}
          {i < steps.length - 1 && <span className="instructions-flow-arrow">→</span>}
        </span>
      ))}
    </div>
  );
}

export default function Instructions() {
  return (
    <AppShell>
      <div className="page-header">
        <h1>Instructions</h1>
        <p className="page-subtitle">How to use this application.</p>
      </div>

      <div className="ingest-cards instructions-cards">
        <div className="ingest-card">
          <h3>Using the app</h3>
          <FlowBar steps={["Login", "RAG Chatbot", "Document Ingestion", "Chat", "Tracing", "Documents"]} />
          <ol className="instructions-list">
            <li>
              <strong>Login</strong> — sign up (first time) or log in with your email and password.
            </li>
            <li>
              <strong>RAG Chatbot</strong> — on the Projects page, click the <em>RAG Chatbot</em> card. This opens
              the chatbot workspace, with <em>Document Ingestion</em>, <em>Chat</em>, <em>Tracing</em>, and{" "}
              <em>Documents</em> in its left sidebar.
            </li>
            <li>
              <strong>Document Ingestion</strong> — choose a file (PDF, XLSX, DOCX, or TXT) → optionally uncheck any
              PII types you don't want masked → click <em>Ingest document</em> → wait for the success message. Do
              this first — Chat has nothing to answer from until a document is ingested.
            </li>
            <li>
              <strong>Chat</strong> — type a question about your uploaded document and press <em>Send</em>. Answers
              are generated only from documents <em>you</em> uploaded. Click <em>+ New chat</em> any time to start a
              fresh conversation without losing your document history.
            </li>
            <li>
              <strong>Tracing</strong> — open a past message's logs to see every guardrail check it went through
              (PII masking, quota, groundedness, and the rest).
            </li>
            <li>
              <strong>Documents</strong> — lists everything you've ingested so far.
            </li>
          </ol>
        </div>

        <div className="ingest-card">
          <h3>Admin: tuning guardrails</h3>
          <p className="gr-field-hint">Visible to everyone for reference — only admins can actually use this.</p>
          <FlowBar steps={["Guardrails Observability", "Guardrails", "Tune Guardrails"]} />
          <ol className="instructions-list">
            <li>
              <strong>Guardrails Observability</strong> — on the Projects page, click the{" "}
              <em>Guardrails Observability</em> card.
            </li>
            <li>
              <strong>Guardrails</strong> — click the <em>Guardrails</em> tab in its left sidebar.
            </li>
            <li>
              <strong>Tune Guardrails</strong> — adjust thresholds and lists (input/output PII detection, per-user
              quotas, model safety, and more), then click <em>Save changes</em>. Click <em>Reset to defaults</em> to
              undo everything back to factory settings.
            </li>
          </ol>
          <p className="gr-field-hint">
            The same project also has a <em>Users</em> tab (grant people access to <code>ragchatbot</code> or{" "}
            <code>guardrail-traces</code>) and a <em>Tracing</em> tab (every user's conversations and the guardrail
            checks they went through).
          </p>
        </div>
      </div>
    </AppShell>
  );
}
