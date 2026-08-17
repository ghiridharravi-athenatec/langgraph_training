import { useEffect, useState } from "react";
import api, { formatErrorDetail } from "../api/client";
import AppShell from "../components/AppShell";
import { useAuth } from "../context/AuthContext";

export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [status, setStatus] = useState("loading");
  const [savingKey, setSavingKey] = useState(null);
  const [error, setError] = useState("");

  const [newProject, setNewProject] = useState({ id: "", name: "", description: "" });
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectFormError, setProjectFormError] = useState("");
  const [projectFormOpen, setProjectFormOpen] = useState(false);

  async function loadAll() {
    setStatus("loading");
    try {
      const [usersRes, projectsRes] = await Promise.all([api.get("/admin/users"), api.get("/admin/projects")]);
      setUsers(usersRes.data);
      setProjects(projectsRes.data);
      setStatus("ready");
    } catch (err) {
      setError(formatErrorDetail(err, "Failed to load admin data."));
      setStatus("error");
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function togglePermission(user, projectId, checked) {
    const key = `${user.id}:${projectId}`;
    const nextProjects = checked
      ? [...user.projects, projectId]
      : user.projects.filter((p) => p !== projectId);

    setSavingKey(key);
    setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, projects: nextProjects } : u)));

    try {
      await api.put(`/admin/users/${user.id}/permissions`, { projects: nextProjects });
    } catch (err) {
      // Roll back on failure.
      setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, projects: user.projects } : u)));
      setError(formatErrorDetail(err, "Failed to update permission."));
    } finally {
      setSavingKey(null);
    }
  }

  async function toggleRole(user) {
    const nextRole = user.role === "admin" ? "user" : "admin";
    const key = `role:${user.id}`;

    setSavingKey(key);
    setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, role: nextRole } : u)));

    try {
      await api.put(`/admin/users/${user.id}/role`, { role: nextRole });
    } catch (err) {
      // Roll back on failure.
      setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, role: user.role } : u)));
      setError(formatErrorDetail(err, "Failed to update role."));
    } finally {
      setSavingKey(null);
    }
  }

  async function handleCreateProject(e) {
    e.preventDefault();
    setProjectFormError("");
    setCreatingProject(true);
    try {
      await api.post("/admin/projects", newProject);
      setNewProject({ id: "", name: "", description: "" });
      setProjectFormOpen(false);
      await loadAll();
    } catch (err) {
      setProjectFormError(formatErrorDetail(err, "Failed to register project."));
    } finally {
      setCreatingProject(false);
    }
  }

  return (
    <AppShell wide>
      <div className="page-header page-header-row">
        <div>
          <h1>Users &amp; Permissions</h1>
          <p className="page-subtitle">Grant or revoke project access. Every project column here is loaded from the backend — nothing is hardcoded.</p>
        </div>
        <button className="btn-secondary" onClick={() => setProjectFormOpen((v) => !v)}>
          {projectFormOpen ? "Cancel" : "Register project"}
        </button>
      </div>

      {projectFormOpen && (
        <form onSubmit={handleCreateProject} className="admin-project-form">
          <label className="field">
            <span className="field-label">Project id (slug)</span>
            <input
              value={newProject.id}
              onChange={(e) => setNewProject((p) => ({ ...p, id: e.target.value }))}
              placeholder="document-search"
              required
            />
          </label>
          <label className="field">
            <span className="field-label">Display name</span>
            <input
              value={newProject.name}
              onChange={(e) => setNewProject((p) => ({ ...p, name: e.target.value }))}
              placeholder="Document Search"
              required
            />
          </label>
          <label className="field field-wide">
            <span className="field-label">Description</span>
            <input
              value={newProject.description}
              onChange={(e) => setNewProject((p) => ({ ...p, description: e.target.value }))}
              placeholder="Optional"
            />
          </label>
          <button type="submit" className="btn-primary" disabled={creatingProject}>
            {creatingProject ? "Registering…" : "Register"}
          </button>
          {projectFormError && <div className="form-error">{projectFormError}</div>}
        </form>
      )}

      {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}
      {status === "loading" && <p className="muted">Loading…</p>}

      {status === "ready" && (
        <div className="table-scroll">
          <table className="permission-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                {projects.map((project) => (
                  <th key={project.id}>{project.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.email}</td>
                  <td className="role-cell">
                    <span className={`role-badge ${user.role === "admin" ? "role-badge-admin" : ""}`}>{user.role}</span>
                    {currentUser?.id === user.id ? (
                      <span className="muted role-toggle-hint">(you)</span>
                    ) : (
                      <button
                        type="button"
                        className="btn-ghost role-toggle-btn"
                        disabled={savingKey === `role:${user.id}`}
                        onClick={() => toggleRole(user)}
                      >
                        {user.role === "admin" ? "Remove admin" : "Make admin"}
                      </button>
                    )}
                  </td>
                  {projects.map((project) => {
                    const key = `${user.id}:${project.id}`;
                    const isAdmin = user.role === "admin";
                    const checked = isAdmin || user.projects.includes(project.id);
                    return (
                      <td key={project.id} className="permission-cell">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={isAdmin || savingKey === key}
                          title={isAdmin ? "Admins have full access to every project" : undefined}
                          onChange={(e) => togglePermission(user, project.id, e.target.checked)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
