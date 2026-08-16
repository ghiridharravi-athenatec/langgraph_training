import { useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErrorDetail } from "../api/client";

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

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-mark">✦</div>
        <h1 className="auth-title">Reset your password</h1>
        <p className="auth-subtitle">Enter your account email and we'll send you a reset link.</p>

        {status === "done" ? (
          <p className="sidebar-status-ok">
            If that email is registered, a reset link is on its way — check your inbox.
          </p>
        ) : (
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

            <button type="submit" className="btn-primary btn-block" disabled={status === "submitting"}>
              {status === "submitting" ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}

        <p className="auth-switch">
          {status === "done" ? (
            <Link to="/login">Back to log in</Link>
          ) : (
            <>
              Remembered it? <Link to="/login">Log in</Link>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
