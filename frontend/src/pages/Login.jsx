import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { formatErrorDetail } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { isValidEmail } from "../utils/validation";
import pkg from "../../package.json";

const TAGLINES = [
  "Grounded in your own documents.",
  "Every turn runs through PII masking.",
  "Quota, groundedness, and safety - checked live.",
  "Nothing answered without a traceable source.",
  "Local PII detection - nothing leaves your server.",
];

const HOW_IT_WORKS = [
  {
    icon: "▤",
    title: "Upload a document",
    desc: "PDF, XLSX, DOCX, or TXT — only you can retrieve from what you upload.",
  },
  {
    icon: "◧",
    title: "Ask a question",
    desc: "Plain language, answered only from your own ingested content.",
  },
  {
    icon: "▣",
    title: "Get a guardrailed answer",
    desc: "PII masked, groundedness checked, every step traceable.",
  },
  {
    icon: "≋",
    title: "Review the trace",
    desc: "Every check the turn passed through, laid out stage by stage.",
  },
];

const FEATURE_HIGHLIGHTS = [
  "20+ automated guardrail checks",
  "Per-user document isolation",
  "Live per-turn tracing",
  "Admin-tunable thresholds",
];

const GUARDRAIL_CHECKS = ["PII masked", "Groundedness verified", "Quota checked"];

function TaglineRotator() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setIndex((i) => (i + 1) % TAGLINES.length), 3200);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="auth-tagline-rotator">
      <p key={index} className="auth-tagline">
        {TAGLINES[index]}
      </p>
    </div>
  );
}

function DemoConversation() {
  const [step, setStep] = useState(0);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timers = [];

    function cycle() {
      if (cancelled) return;
      setFading(false);
      setStep(0);
      timers.push(setTimeout(() => !cancelled && setStep(1), 400));
      timers.push(setTimeout(() => !cancelled && setStep(2), 1400));
      timers.push(setTimeout(() => !cancelled && setStep(3), 2400));
      timers.push(setTimeout(() => !cancelled && setStep(4), 3400));
      timers.push(setTimeout(() => !cancelled && setStep(5), 5100));
      timers.push(setTimeout(() => !cancelled && setFading(true), 8400));
      timers.push(setTimeout(cycle, 9100));
    }

    cycle();
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, []);

  return (
    <div className={`auth-demo-card ${fading ? "auth-demo-fading" : ""}`}>
      {step >= 1 && (
        <div className="auth-demo-doc-row animate-in">
          <span className="auth-demo-doc-icon">▤</span>
          <span>report.pdf ingested</span>
          <span className="auth-demo-check">✓</span>
        </div>
      )}

      {step >= 2 && (
        <div className="auth-demo-bubble-row animate-in">
          <span className="auth-demo-bubble">What was Q3 revenue?</span>
        </div>
      )}

      {step === 3 && (
        <div className="auth-demo-typing-row animate-in">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      )}

      {step >= 4 && (
        <div className="auth-demo-answer-row">
          <span className="auth-demo-answer-typeline">Q3 revenue was $4.2M, up 12% QoQ.</span>
        </div>
      )}

      {step >= 5 && (
        <div className="auth-demo-checks-row">
          {GUARDRAIL_CHECKS.map((check, i) => (
            <span key={check} className="auth-demo-check-pill animate-in" style={{ animationDelay: `${i * 180}ms` }}>
              <span className="auth-demo-check">✓</span>
              {check}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

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
    <div className="auth-page auth-page-split">
      <div className="auth-illustration">
        <div className="auth-showcase">
          <div className="auth-showcase-header">
            <div className="auth-mark-lg">✦</div>
            <div>
              <div className="auth-showcase-title">AI Assistance</div>
              <div className="auth-badge-row">
                <span className="auth-version-badge">v{pkg.version}</span>
                <span className="auth-live-badge">
                  <span className="auth-live-dot" />
                  Guardrails active
                </span>
              </div>
            </div>
          </div>

          <TaglineRotator />

          <DemoConversation />

          <ol className="auth-steps">
            {HOW_IT_WORKS.map((s, i) => (
              <li key={s.title} className="animate-in" style={{ animationDelay: `${i * 120}ms` }}>
                <span className="auth-step-icon">{s.icon}</span>
                <div>
                  <div className="auth-step-title">{s.title}</div>
                  <div className="auth-step-desc">{s.desc}</div>
                </div>
              </li>
            ))}
          </ol>

          <div className="auth-feature-strip">
            {FEATURE_HIGHLIGHTS.map((label, i) => (
              <span key={label} className="auth-feature-chip animate-in" style={{ animationDelay: `${i * 90}ms` }}>
                {label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <div className="auth-mark">✦</div>
          <span className="auth-eyebrow">Guardrails Demonstration</span>
          <h1 className="auth-title">Welcome back</h1>
          <p className="auth-subtitle">Log in to continue to AI Assistance</p>

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

            <button type="submit" className="btn-primary btn-block" disabled={submitting}>
              {submitting ? "Logging in…" : "Log in"}
            </button>
          </form>

          <p className="auth-switch">
            Don't have an account? <Link to="/signup">Sign up</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
