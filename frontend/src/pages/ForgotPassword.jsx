import { useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErrorDetail } from "../api/client";
import ThemeToggle from "../components/ThemeToggle";
import AuthContentPanel from "../components/AuthContentPanel";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | submitting | done
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setStatus("submitting");
    try {
      await api.post("/auth/forgot-password", { email });
      setStatus("done");
    } catch (err) {
      setError(formatErrorDetail(err));
      setStatus("idle");
    }
  }

  const done = status === "done";

  return (
    <div className="auth-page-split">
      <ThemeToggle floating />

      <div className="auth-form-panel">
        <div className="auth-form-inner">
          <div className="auth-form-brand">
            <span className="auth-form-mark">✦</span>
            <span className="auth-form-wordmark">AI Assistance</span>
          </div>

          <h1 className="auth-title">Reset your password</h1>
          <p className="auth-switch-inline">
            {done ? (
              <Link to="/login">Back to log in</Link>
            ) : (
              <>
                Remembered it? <Link to="/login">Log in</Link>
              </>
            )}
          </p>

          {done ? (
            <p className="sidebar-status-ok">
              If that email is registered, a reset link is on its way — check your inbox.
            </p>
          ) : (
            <>
              <p className="auth-subtitle">Enter your account email and we'll send you a reset link.</p>

              <form onSubmit={handleSubmit} className="auth-form">
                <label className="field">
                  <span className="field-label">Email</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    autoFocus
                  />
                </label>

                {error && <div className="form-error">{error}</div>}

                <button type="submit" className="btn-primary btn-block auth-submit-btn" disabled={status === "submitting"}>
                  {status === "submitting" ? "Sending…" : "Send reset link"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>

      <AuthContentPanel
        eyebrow="Account security"
        heading="Your account, protected end to end."
        body="Reset links are single-use and expire quickly. We never email your password, and every login attempt - successful or not - is rate-limited and logged."
        features={[
          { icon: "▣", label: "Passwords are hashed, never stored or emailed in plain text" },
          { icon: "≋", label: "Reset links are single-use and expire automatically" },
          { icon: "⛁", label: "Repeated failed attempts are rate-limited" },
        ]}
        stat="Every attempt is logged and rate-limited"
      />
    </div>
  );
}
