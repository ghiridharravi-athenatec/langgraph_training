import { useState } from "react";
import AppShell from "../components/AppShell";
import { formatErrorDetail } from "../api/client";
import { useAuth } from "../context/AuthContext";

export default function Account() {
  const { user, changePassword } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (newPassword !== confirmPassword) {
      setError("New passwords don't match.");
      return;
    }

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setSuccess("Password changed. Your other sessions have been logged out.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(formatErrorDetail(err, "Failed to change password."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <h1>Account</h1>
        <p className="page-subtitle">{user?.email}</p>
      </div>

      <div className="ingest-cards">
        <div className="ingest-card">
          <h3>Change password</h3>
          <form onSubmit={handleSubmit} className="sidebar-form">
            <label className="field">
              <span className="field-label">Current password</span>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="••••••••"
                required
                autoFocus
              />
            </label>

            <label className="field">
              <span className="field-label">New password</span>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="At least 8 characters, with a letter and a number"
                required
                minLength={8}
              />
            </label>

            <label className="field">
              <span className="field-label">Confirm new password</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                required
                minLength={8}
              />
            </label>

            {error && <div className="form-error">{error}</div>}
            {success && <p className="sidebar-status-ok">{success}</p>}

            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? "Updating…" : "Update password"}
            </button>
          </form>
        </div>
      </div>
    </AppShell>
  );
}
