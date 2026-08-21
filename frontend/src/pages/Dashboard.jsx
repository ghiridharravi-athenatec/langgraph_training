import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import AppShell from "../components/AppShell";
import { useAuth } from "../context/AuthContext";

// Real project ids this app actually ships (see ProjectView.jsx's routing) -
// everything else genuinely renders ProjectPlaceholder's "IN DEVELOPMENT"
// screen, so the fallback meta below reflects that honestly instead of
// pretending every card is a finished feature.
const PROJECT_META = {
  ragchatbot: { tag: "Document chat", icon: "▤", accent: "document" },
  "database-chatbot": { tag: "Database chat", icon: "⛁", accent: "database" },
  "guardrail-traces": { tag: "Observability", icon: "≋", accent: "guardrails" },
  "ai-search": { tag: "In Development", icon: "◈", accent: "search" },
};
const FALLBACK_META = { tag: "In development", icon: "◧", accent: "muted" };

function greetingName(email) {
  if (!email) return "";
  const local = email.split("@")[0];
  return local.charAt(0).toUpperCase() + local.slice(1);
}

export default function Dashboard() {
  const { user, isAdmin } = useAuth();
  const [projects, setProjects] = useState([]);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .get("/projects")
      .then(({ data }) => {
        if (!cancelled) {
          setProjects(data);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell wide>
      <div className="dashboard-hero">
        <div className="dashboard-hero-shapes" aria-hidden="true">
          <span className="dashboard-hero-shape dashboard-hero-shape-1">✦</span>
          <span className="dashboard-hero-shape dashboard-hero-shape-2">▤</span>
          <span className="dashboard-hero-shape dashboard-hero-shape-3">≋</span>
        </div>
        <div className="dashboard-hero-inner">
          <span className="dashboard-hero-eyebrow animate-in">
            {isAdmin ? "Admin access" : "Your workspace"}
          </span>
          <h1 className="dashboard-hero-heading animate-in" style={{ animationDelay: "60ms" }}>
            Welcome back{user?.email ? `, ${greetingName(user.email)}` : ""}.
          </h1>
          <p className="dashboard-hero-body animate-in" style={{ animationDelay: "120ms" }}>
            Every project below runs through the same guardrail pipeline - PII masking, quota,
            safety, and groundedness checks - before an answer ever reaches you.
          </p>
          <div className="dashboard-hero-stats animate-in" style={{ animationDelay: "200ms" }}>
            <span className="dashboard-hero-stat">
              <span className="dashboard-hero-stat-dot" />
              {status === "ready" ? `${projects.length} project${projects.length === 1 ? "" : "s"} available` : "Loading projects…"}
            </span>
            <span className="dashboard-hero-stat">20+ automated guardrail checks, every request</span>
            <Link to="/instructions" className="dashboard-hero-link">
              See how it works →
            </Link>
          </div>
        </div>
      </div>

      <div className="page-header dashboard-projects-header">
        <h2 className="dashboard-section-heading">Your projects</h2>
        <p className="page-subtitle">
          {isAdmin ? "Every enabled project — admins have full access." : "Projects an admin has granted you access to."}
        </p>
      </div>

      {status === "loading" && <p className="muted">Loading projects…</p>}
      {status === "error" && <p className="form-error">Couldn't load your projects. Try refreshing.</p>}

      {status === "ready" && projects.length === 0 && (
        <div className="empty-state">
          <p>No projects yet.</p>
          <p className="muted">Ask an admin to grant you access to a project.</p>
        </div>
      )}

      {status === "ready" && projects.length > 0 && (
        <div className="project-grid">
          {projects.map((project, i) => {
            const meta = PROJECT_META[project.id] || FALLBACK_META;
            return (
              <Link
                to={`/projects/${project.id}`}
                key={project.id}
                className={`project-card project-card-${meta.accent}`}
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <div className="project-card-top">
                  <div className="project-card-icon">{meta.icon}</div>
                  <span className="project-card-tag">{meta.tag}</span>
                </div>
                <div className="project-card-name">{project.name}</div>
                <div className="project-card-desc">{project.description || "No description provided."}</div>
                <span className="project-card-cta">Open →</span>
              </Link>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
