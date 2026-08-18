import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { formatErrorDetail } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { isValidEmail } from "../utils/validation";
import ThemeToggle from "../components/ThemeToggle";
import AuthContentPanel from "../components/AuthContentPanel";

// Demo-only quick sign-in - fills the form fields below, doesn't submit on its
// own, so the normal login flow (validation, error handling) still runs.
const DEMO_ACCOUNTS = [
  { label: "Admin", email: "admin@example.com", password: "Admin@123456" },
  { label: "Data Loader", email: "dataloader@example.com", password: "DataLoader@123456" },
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const from = location.state?.from?.pathname || "/";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!isValidEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }

    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(formatErrorDetail(err));
    } finally {
      setSubmitting(false);
    }
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
          <span className="auth-eyebrow">Guardrails Demonstration</span>

          <h1 className="auth-title">Welcome back</h1>
          <p className="auth-switch-inline">
            Don't have an account? <Link to="/signup">Sign up</Link>
          </p>

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

            <label className="field">
              <span className="field-label">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </label>

            <div className="auth-forgot-link">
              <Link to="/forgot-password">Forgot password?</Link>
            </div>

            {error && <div className="form-error">{error}</div>}

            <button type="submit" className="btn-primary btn-block auth-submit-btn" disabled={submitting}>
              {submitting ? "Logging in…" : "Log in"}
            </button>
          </form>

          <div className="auth-divider">
            <span>or quick sign-in</span>
          </div>
          <div className="auth-quick-signin-row">
            {DEMO_ACCOUNTS.map((account) => (
              <button
                key={account.email}
                type="button"
                className="auth-quick-signin-link"
                onClick={() => {
                  setEmail(account.email);
                  setPassword(account.password);
                  setError("");
                }}
              >
                {account.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <AuthContentPanel />
    </div>
  );
}
