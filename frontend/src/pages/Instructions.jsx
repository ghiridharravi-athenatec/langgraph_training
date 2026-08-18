import { useState } from "react";
import AppShell from "../components/AppShell";

const TABS = [
  { id: "pipeline", label: "Architecture" },
  { id: "scenarios", label: "Scenarios" },
];

// ---------------------------------------------------------------------------
// Architecture flow diagram - the actual request path through both chatbots,
// built from the real pipeline (app/api/v1/api.py + app/utils/retrieve.py for
// documents, app/api/v1/database.py + app/core/db_agent.py for the database).
// "gate" nodes are guardrail checks that can block the turn; plain nodes are
// ordinary processing steps.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Setup flows - getting a document or a database connection into the system
// in the first place. Independent of each other and of the chat pipeline
// below (see POST /ingest in app/api/v1/api.py and POST /database/connections
// in app/api/v1/database.py) - a document only needs to go through Document
// Ingestion once; a connection only needs to be added once.
// ---------------------------------------------------------------------------

const SETUP_INGEST_FLOW = [
  {
    title: "User uploads a file",
    desc: "PDF, XLSX, DOCX, or TXT - from the Data Ingestion tab, with an optional per-upload PII entity list",
  },
  {
    title: "File size check",
    desc: "Rejects anything over the configured upload size limit",
    gate: true,
  },
  {
    title: "File type check",
    desc: "Magic-byte sniff, not just the extension - a renamed or malformed file is rejected even if its name looks right",
    gate: true,
  },
  {
    title: "Extract & chunk",
    desc: "Per-format extraction (PDF text/tables/OCR'd images, XLSX sheets, DOCX paragraphs/tables, plain text), split into ~700-character overlapping chunks",
  },
  {
    title: "PII masking",
    desc: "Same Presidio/spaCy detector used on chat - every chunk masked before it's ever embedded, using the uploader's chosen entity list",
    gate: true,
  },
  {
    title: "Embed & store",
    desc: "Chunks embedded (BGE-M3) and stored, scoped to this uploader only - nobody else's retrieval will ever see them",
  },
];

const SETUP_DB_CONNECTION_FLOW = [
  {
    title: "User submits connection details",
    desc: "A connection string, or host/port/username/password/database - from the Connections tab",
  },
  {
    title: "Live connection test",
    desc: "Actually connects and lists tables/collections before anything is saved - a connection that can't be reached is rejected outright, never persisted",
    gate: true,
  },
  {
    title: "Encrypt at rest",
    desc: "Credentials Fernet-encrypted before being persisted - nothing is ever stored in plaintext",
    gate: true,
  },
  {
    title: "Saved",
    desc: "Available to the Database Chatbot from then on - every query still runs through the same read-only enforcement shown below",
  },
];

const PIPELINE_SHARED_TOP = [
  {
    title: "User",
    desc: "Conversational Assistant or Database Chatbot - same chat UI pattern either way",
  },
  {
    title: "POST /chat or /database/chat",
    desc: "Question + conversation id + selected model, sent over HTTPS with a JWT",
  },
  {
    title: "Input validation",
    desc: "Length bounds · prompt-injection regex · blocked keywords · PII detection & masking (Presidio/spaCy, reversibly encrypted)",
    gate: true,
  },
  {
    title: "Daily token quota",
    desc: "Blocks once today's usage reaches this user's quota - admins included, no exemption",
    gate: true,
  },
];

const PIPELINE_DOC_BRANCH = [
  {
    title: "Knowledge base check",
    desc: "Blocks the entire turn, including greetings, if this user hasn't ingested any documents of their own yet",
    gate: true,
  },
  {
    title: "Intent classification",
    desc: "Model safety classifier · prompt-injection (model judgment) · topic restriction (only if an admin configured approved topics) · greeting vs. question",
    gate: true,
  },
  {
    title: "Semantic cache",
    desc: "Reuses a past answer directly if a highly similar question (≥0.93 cosine similarity) was already asked - skips retrieval and generation entirely",
  },
  {
    title: "Hybrid retrieval",
    desc: "Dense (Atlas vector search) + BM25, fused by reciprocal rank - scoped to this user's own ingested documents only",
  },
  {
    title: "Retrieval validation",
    desc: "Drops chunks below the relevance-score threshold, keeps at most the top N",
    gate: true,
  },
  {
    title: "Context budget",
    desc: "Trims retrieved text to a character budget, dropping the lowest-ranked chunks first",
  },
  {
    title: "Answer generation",
    desc: "Answers from the retrieved context only - never outside knowledge. Self-reports bias, if enabled by an admin",
    gate: true,
  },
  {
    title: "Groundedness check",
    desc: "Blocks the answer if its embedding isn't similar enough to the retrieved context - i.e. it isn't well-supported by the documents",
    gate: true,
  },
];

const PIPELINE_DB_BRANCH = [
  {
    title: "Database agent",
    desc: "Tool-calling loop (Sonnet/GPT) against the connected database, aware of prior conversation turns, capped at a fixed number of tool calls",
    gate: true,
  },
  {
    title: "Query execution - read-only by construction",
    desc: "Single statement only, SELECT-only, any write/DDL keyword rejected before it ever reaches the database - there is no destructive tool to call in the first place",
    gate: true,
  },
];

const PIPELINE_SHARED_BOTTOM = [
  {
    title: "Output validation",
    desc: "Not empty · blocked keywords · compliance keywords · PII masking · link allowlist · length limit · tone flag (advisory, never blocks)",
    gate: true,
  },
  {
    title: "User",
    desc: "Sees the answer - every check above (passed, failed, or skipped) is visible via View Trace or the Tracing tab",
  },
];

function PipelineNode({ node }) {
  return (
    <div className={`pipeline-node ${node.gate ? "pipeline-node-gate" : ""}`}>
      {node.gate && <span className="pipeline-node-eyebrow">Guardrail check</span>}
      <div className="pipeline-node-title">{node.title}</div>
      <div className="pipeline-node-desc">{node.desc}</div>
    </div>
  );
}

function PipelineArrow({ label }) {
  return (
    <div className="pipeline-arrow">
      <span className="pipeline-arrow-line" />
      {label && <span className="pipeline-arrow-label">{label}</span>}
    </div>
  );
}

function PipelineColumn({ nodes }) {
  return (
    <div className="pipeline-branch-col">
      {nodes.map((node, i) => (
        <div key={node.title} className="pipeline-node-wrap">
          {i > 0 && <PipelineArrow />}
          <PipelineNode node={node} />
        </div>
      ))}
    </div>
  );
}

function SetupDiagram() {
  return (
    <div className="pipeline-branch-row">
      <div className="pipeline-branch">
        <span className="pipeline-branch-header">Document Ingestion</span>
        <PipelineColumn nodes={SETUP_INGEST_FLOW} />
      </div>
      <div className="pipeline-branch">
        <span className="pipeline-branch-header">Database Connection</span>
        <PipelineColumn nodes={SETUP_DB_CONNECTION_FLOW} />
      </div>
    </div>
  );
}

function PipelineDiagram() {
  return (
    <div className="pipeline-diagram">
      {PIPELINE_SHARED_TOP.map((node, i) => (
        <div key={node.title} className="pipeline-node-wrap">
          {i > 0 && <PipelineArrow />}
          <PipelineNode node={node} />
        </div>
      ))}

      <PipelineArrow label="branches by which chatbot you're using" />

      <div className="pipeline-branch-row">
        <div className="pipeline-branch">
          <span className="pipeline-branch-header">Conversational Assistant</span>
          <PipelineColumn nodes={PIPELINE_DOC_BRANCH} />
        </div>
        <div className="pipeline-branch">
          <span className="pipeline-branch-header">Database Chatbot</span>
          <PipelineColumn nodes={PIPELINE_DB_BRANCH} />
          <p className="pipeline-branch-note">
            Deliberately thinner than the document path - there's no retrieval, cache, or
            groundedness check to run, since a query either returns real rows or nothing.
          </p>
        </div>
      </div>

      <PipelineArrow label="both paths converge" />

      {PIPELINE_SHARED_BOTTOM.map((node) => (
        <div key={node.title} className="pipeline-node-wrap">
          <PipelineArrow />
          <PipelineNode node={node} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scenarios - real guardrail behavior, one per card. Trace lines and user-
// facing text are the actual messages this app produces (see app/core/
// messages.yml and app/core/guardrails.py), not invented copy.
// ---------------------------------------------------------------------------

const SCENARIOS = [
  {
    n: "01",
    tag: "Input · Model-based",
    title: "Off-topic questions never reach retrieval at all",
    question: "What's your take on the upcoming election?",
    trace: [
      "input validation → passed",
      "intent classification → topic_restriction: BLOCKED (outside the approved topics: billing, product usage, warranty)",
      "blocked before retrieval or generation ever run",
    ],
    answer:
      "I can't process this: This question falls outside the topics this assistant is configured to answer.",
    note:
      "Off by default - only activates once an admin configures an approved-topics list on the Guardrails page. Judged by the model riding on the same call as intent classification, not a separate round-trip.",
  },
  {
    n: "02",
    tag: "Output · Model-based",
    title: "PII is masked automatically, on every answer",
    question: "Give me the email address of Ghiridhar?",
    trace: [
      "input validation → passed",
      "retrieval → 3 chunks from your own documents",
      "answer generated from context",
      "output validation → PII masked: PERSON, EMAIL_ADDRESS, PHONE_NUMBER",
    ],
    answer:
      "The email address of PII:PERSON is PII:EMAIL_ADDRESS.",
    note:
      "The real value isn't dropped - it's reversibly encrypted into the token, not just redacted. This runs on every answer, not just ones that look sensitive.",
  },
  {
    n: "03",
    tag: "Input · Deterministic",
    title: "Blocked before the model is ever called",
    question: "Summarize the entire onboarding handbook, section by section.",
    trace: [
      "input validation → passed",
      "daily token quota → 50,000/50,000 tokens already used today → BLOCKED",
      "blocked before intent classification, retrieval, or generation ever run",
    ],
    answer:
      "I can't process this: You've used your full daily token quota (50,000/50,000). It resets tomorrow, or ask an admin to raise your limit.",
    note: "Checked using whatever usage has already accumulated today, before the expensive model calls run - applies uniformly, admins included.",
  },
  {
    n: "04",
    tag: "Retrieval · Model-based",
    title: "Nothing relevant enough to answer from",
    question: "What's the process for filing an expense report in Japan?",
    trace: [
      "input validation → passed",
      "retrieval → 4 chunks fetched, all below the 0.35 relevance-score threshold",
      "retrieval validation → BLOCKED (no chunks cleared the minimum relevance score)",
    ],
    answer:
      "I couldn't find anything in your documents that's closely related to this question. Try rephrasing it, or confirm the right document has been uploaded.",
    note: "The relevance-score threshold is admin-tunable on the Guardrails page - each chunk's score comes from the same hybrid search that retrieved it, not a separate guess.",
  },
];

function ScenarioCard({ scenario }) {
  return (
    <div className="scenario-card">
      <div className="scenario-card-head">
        <span className="scenario-card-number">Scenario {scenario.n}</span>
        <span className="scenario-card-tag">{scenario.tag}</span>
      </div>
      <h4 className="scenario-card-title">{scenario.title}</h4>
      <p className="scenario-card-question">“{scenario.question}”</p>
      <div className="scenario-card-trace">
        {scenario.trace.map((line) => (
          <div key={line} className="scenario-card-trace-line">
            <span className="scenario-card-trace-arrow">→</span> {line}
          </div>
        ))}
      </div>
      <p className="scenario-card-answer">{scenario.answer}</p>
      {scenario.note && <p className="scenario-card-note">{scenario.note}</p>}
    </div>
  );
}

export default function Instructions() {
  const [activeTab, setActiveTab] = useState("pipeline");

  return (
    <AppShell>
      <div className="page-header">
        <h1>Instructions</h1>
        <p className="page-subtitle">How a request flows through the system, and what the guardrails actually do.</p>
      </div>

      <div className="instructions-tab-switch">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`instructions-tab-btn ${activeTab === tab.id ? "instructions-tab-btn-active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="ingest-cards instructions-cards">
        {activeTab === "scenarios" && (
          <div className="ingest-card">
            <h3>Scenarios</h3>
            <p className="gr-field-hint">
              Four real examples of the guardrails actually deciding something - the question asked, the checks
              it passed through, and exactly what the user sees.
            </p>
            <div className="scenario-list">
              {SCENARIOS.map((scenario) => (
                <ScenarioCard key={scenario.n} scenario={scenario} />
              ))}
            </div>
          </div>
        )}

        {activeTab === "pipeline" && (
          <div className="ingest-card">
            <h3>Architecture: how a request flows through the system</h3>
            <p className="gr-field-hint">
              Every box below is a real stage in the actual pipeline - accent-bordered boxes are guardrail checks
              that can block a turn; plain boxes are ordinary processing steps.
            </p>

            <h4 className="pipeline-subheading">Getting data in</h4>
            <p className="gr-field-hint">
              Two independent, one-time setup flows - a document only needs to go through Document Ingestion
              once; a database connection only needs to be added once.
            </p>
            <SetupDiagram />

            <h4 className="pipeline-subheading">Then, every chat turn</h4>
            <PipelineDiagram />
          </div>
        )}
      </div>
    </AppShell>
  );
}
