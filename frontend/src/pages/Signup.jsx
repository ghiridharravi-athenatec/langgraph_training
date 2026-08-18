import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { formatErrorDetail } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { isValidEmail } from "../utils/validation";
import ThemeToggle from "../components/ThemeToggle";

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!isValidEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }

    setSubmitting(true);
    try {
      await signup(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(formatErrorDetail(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <ThemeToggle floating />
      <div className="auth-card">
        <div className="auth-mark">✦</div>
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-subtitle">
          You'll start with no project access — an admin grants it once you're signed up.
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
              placeholder="At least 8 characters, with a letter and a number"
              required
              minLength={8}
            />
          </label>

          {error && <div className="form-error">{error}</div>}

          <button type="submit" className="btn-primary btn-block" disabled={submitting}>
            {submitting ? "Creating account…" : "Sign up"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
