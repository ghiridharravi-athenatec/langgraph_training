import { useEffect, useState } from "react";
import api, { formatErrorDetail } from "../api/client";

const ENGINE_OPTIONS = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "mssql", label: "SQL Server" },
  { value: "mongodb", label: "MongoDB" },
];

const EMPTY_FORM = {
  name: "",
  engine: "postgresql",
  host: "",
  port: "",
  username: "",
  password: "",
  database: "",
};

export default function DatabaseIngestPanel({ onConnectionsChanged }) {
  const [connections, setConnections] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  const [useConnectionString, setUseConnectionString] = useState(false);
  const [connectionString, setConnectionString] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [connecting, setConnecting] = useState(false);
  const [formError, setFormError] = useState("");
  const [editingId, setEditingId] = useState(null);

  async function loadConnections() {
    setStatus("loading");
    try {
      const { data } = await api.get("/database/connections");
      setConnections(data);
      setStatus("ready");
      onConnectionsChanged?.(data);
    } catch (err) {
      setError(formatErrorDetail(err, "Failed to load database connections."));
      setStatus("error");
    }
  }

  useEffect(() => {
    loadConnections();
  }, []);

  async function handleConnect(e) {
    e.preventDefault();
    setFormError("");
    setConnecting(true);
    try {
      const payload = useConnectionString
        ? { name: form.name, engine: form.engine, connection_string: connectionString }
        : {
            name: form.name,
            engine: form.engine,
            host: form.host,
            port: form.port ? Number(form.port) : null,
            username: form.username,
            password: form.password,
            database: form.database,
          };
      if (editingId) {
        await api.put(`/database/connections/${editingId}`, payload);
      } else {
        await api.post("/database/connections", payload);
      }
      resetForm();
      await loadConnections();
    } catch (err) {
      setFormError(formatErrorDetail(err, editingId ? "Could not save those changes." : "Could not connect to that database."));
    } finally {
      setConnecting(false);
    }
  }

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setConnectionString("");
    setUseConnectionString(false);
    setFormError("");
  }

  function startEditing(connection) {
    setEditingId(connection.id);
    setUseConnectionString(false);
    setConnectionString("");
    // Only name/engine/host/database are ever returned to the client - password,
    // port, username, and any connection string stay write-only, so those fields
    // start blank and must be re-entered in full to save changes.
    setForm({
      name: connection.name,
      engine: connection.engine,
      host: connection.host || "",
      port: "",
      username: "",
      password: "",
      database: connection.database,
    });
    setFormError("");
  }

  async function handleDelete(id) {
    try {
      await api.delete(`/database/connections/${id}`);
      if (editingId === id) resetForm();
      await loadConnections();
    } catch (err) {
      setError(formatErrorDetail(err, "Failed to remove connection."));
    }
  }

  return (
    <div className="ingest-cards">
      <div className="ingest-card sidebar-section">
        <h3>{editingId ? "Edit connection" : "Connect a database"}</h3>
        <form onSubmit={handleConnect} className="sidebar-form">
          {editingId && (
            <span className="gr-field-hint">
              Password, port, and username aren't shown for security - re-enter them to save changes.
            </span>
          )}
          <label className="field">
            <span className="field-label">Connection name</span>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Production Postgres"
              required
            />
          </label>

          <label className="field">
            <span className="field-label">Engine</span>
            <select value={form.engine} onChange={(e) => setForm((f) => ({ ...f, engine: e.target.value }))}>
              {ENGINE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="gr-checkbox-row">
            <input
              type="checkbox"
              checked={useConnectionString}
              onChange={(e) => setUseConnectionString(e.target.checked)}
            />
            Use a connection string instead
          </label>

          {useConnectionString ? (
            <label className="field">
              <span className="field-label">Connection string</span>
              <input
                value={connectionString}
                onChange={(e) => setConnectionString(e.target.value)}
                placeholder="postgresql://user:password@host:5432/dbname"
                required
              />
            </label>
          ) : (
            <>
              <label className="field">
                <span className="field-label">Host</span>
                <input value={form.host} onChange={(e) => setForm((f) => ({ ...f, host: e.target.value }))} required />
              </label>
              <label className="field">
                <span className="field-label">Port (optional)</span>
                <input
                  type="number"
                  value={form.port}
                  onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
                />
              </label>
              <label className="field">
                <span className="field-label">Username</span>
                <input
                  value={form.username}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                  required
                />
              </label>
              <label className="field">
                <span className="field-label">Password</span>
                <input
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                />
              </label>
              <label className="field">
                <span className="field-label">Database</span>
                <input
                  value={form.database}
                  onChange={(e) => setForm((f) => ({ ...f, database: e.target.value }))}
                  required
                />
              </label>
            </>
          )}

          <span className="gr-field-hint">
            Read-only. The agent can only run SELECT-style queries — write/DDL statements are rejected before they
            reach your database.
          </span>

          {formError && <div className="form-error">{formError}</div>}

          <button type="submit" className="btn-secondary btn-block" disabled={connecting}>
            {connecting ? "Saving…" : editingId ? "Save changes" : "Connect"}
          </button>
          {editingId && (
            <button type="button" className="btn-ghost btn-block" onClick={resetForm}>
              Cancel
            </button>
          )}
        </form>
      </div>

      <div className="ingest-card sidebar-section">
        <h3>Your connections</h3>
        <p className="muted">
          Once connected, ask questions about this database from the <strong>Chat</strong> tab — it's automatically
          used alongside any documents you've ingested.
        </p>
        {status === "loading" && <p className="muted">Loading…</p>}
        {status === "error" && <p className="form-error">{error}</p>}
        {status === "ready" && connections.length === 0 && <p className="muted">No databases connected yet.</p>}
        {status === "ready" && connections.length > 0 && (
          <ul className="db-connection-list">
            {connections.map((c) => (
              <li key={c.id} className="db-connection-row">
                <div>
                  <div className="db-connection-name">{c.name}</div>
                  <div className="muted">
                    {c.engine} · {c.database}
                  </div>
                </div>
                <div className="db-connection-actions">
                  <button type="button" className="btn-ghost" onClick={() => startEditing(c)}>
                    Edit
                  </button>
                  <button type="button" className="btn-ghost" onClick={() => handleDelete(c.id)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
