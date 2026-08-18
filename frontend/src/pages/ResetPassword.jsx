import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api, { formatErrorDetail } from "../api/client";
import ThemeToggle from "../components/ThemeToggle";
import AuthContentPanel from "../components/AuthContentPanel";

const RESET_CONTENT_PANEL_PROPS = {
  eyebrow: "Account security",
  heading: "Your account, protected end to end.",
  body: "Reset links are single-use and expire quickly. We never email your password, and every login attempt - successful or not - is rate-limited and logged.",
  features: [
    { icon: "▣", label: "Passwords are hashed, never stored or emailed in plain text" },
    { icon: "≋", label: "Reset links are single-use and expire automatically" },
    { icon: "⛁", label: "Repeated failed attempts are rate-limited" },
  ],
  stat: "Every attempt is logged and rate-limited",
};

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: newPassword });
      setDone(true);
    } catch (err) {
      setError(formatErrorDetail(err, "This reset link is invalid or has expired."));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-page-split">
        <ThemeToggle floating />

        <div className="auth-form-panel">
          <div className="auth-form-inner">
            <div className="auth-form-brand">
              <span className="auth-form-mark">✦</span>
              <span className="auth-form-wordmark">AI Assistance</span>
            </div>

            <h1 className="auth-title">Invalid reset link</h1>
            <p className="auth-switch-inline">
              <Link to="/forgot-password">Request a new reset link</Link>
            </p>
            <p className="auth-subtitle">This link is missing its token. Request a new one to continue.</p>
          </div>
        </div>

        <AuthContentPanel {...RESET_CONTENT_PANEL_PROPS} />
      </div>
    );
  }

  return (
    <div className="auth-page-split">
      <ThemeToggle floating />

      <div className="auth-form-panel">
        <div className="auth-form-inner">
          <div className="auth-form-brand">
            <span className="auth-form-mark">✦</span>
            <span className="auth-form-wordmark">AI Assistance</span>
          </div>

          <h1 className="auth-title">Set a new password</h1>

          {done ? (
            <>
              <p className="auth-switch-inline">
                <Link to="/login">Go to log in</Link>
              </p>
              <p className="sidebar-status-ok">Password updated. You can log in with it now.</p>
            </>
          ) : (
            <>
              <p className="auth-subtitle">Choose a new password for your account.</p>

              <form onSubmit={handleSubmit} className="auth-form">
                <label className="field">
                  <span className="field-label">New password</span>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="At least 8 characters, with a letter and a number"
                    required
                    minLength={8}
                    autoFocus
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

                <button type="submit" className="btn-primary btn-block auth-submit-btn" disabled={submitting}>
                  {submitting ? "Resetting…" : "Reset password"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>

      <AuthContentPanel {...RESET_CONTENT_PANEL_PROPS} />
    </div>
  );
}
