import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import AppShell from "../components/AppShell";
import { useAuth } from "../context/AuthContext";

export default function Dashboard() {
  const { user } = useAuth();
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
    <AppShell>
      <div className="page-header">
        <h1>Projects</h1>
        <p className="page-subtitle">
          {user?.role === "admin"
            ? "Every enabled project — admins have full access."
            : "Projects an admin has granted you access to."}
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
          {projects.map((project) => (
            <Link to={`/projects/${project.id}`} key={project.id} className="project-card">
              <div className="project-card-icon">{project.name.charAt(0).toUpperCase()}</div>
              <div className="project-card-name">{project.name}</div>
              <div className="project-card-desc">{project.description || "No description provided."}</div>
            </Link>
          ))}
        </div>
      )}
    </AppShell>
  );
}
