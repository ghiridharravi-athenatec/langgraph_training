// Shared right-hand (or left-hand, on Login - see .auth-content-panel's CSS
// `order`) marketing panel for every auth page - gradient background, floating
// brand glyphs, staggered entrance. Extracted once it needed to be reused
// across Login/Signup/ForgotPassword/ResetPassword instead of copy-pasted.
const DEFAULT_FEATURES = [
  { icon: "▣", label: "Every answer runs through automated guardrails - PII masking, quota, safety, groundedness" },
  { icon: "≋", label: "Full per-turn tracing - see exactly which checks ran, and why" },
  { icon: "⛁", label: "Chat with your documents, or a live, read-only database" },
];

export default function AuthContentPanel({
  eyebrow = "Guardrails Implementation",
  heading = "How to implement guardrails for LLM applications",
  body = "Every question runs through automated guardrails before and after the model ever sees it - PII masking, quota limits, safety and groundedness checks. Chat with your documents or a live database, and trace exactly what happened, turn by turn.",
  features = DEFAULT_FEATURES,
  stat = "20+ automated guardrail checks, running live",
}) {
  return (
    <div className="auth-content-panel">
      <div className="auth-content-shapes" aria-hidden="true">
        <span className="auth-content-shape auth-content-shape-1">✦</span>
        <span className="auth-content-shape auth-content-shape-2">▤</span>
        <span className="auth-content-shape auth-content-shape-3">◧</span>
        <span className="auth-content-shape auth-content-shape-4">≋</span>
      </div>

      <div className="auth-content-inner">
        <span className="auth-content-eyebrow animate-in">{eyebrow}</span>
        <h2 className="auth-content-heading animate-in" style={{ animationDelay: "60ms" }}>
          {heading}
        </h2>
        <p className="auth-content-body animate-in" style={{ animationDelay: "120ms" }}>
          {body}
        </p>

        {features && features.length > 0 && (
          <ul className="auth-content-features">
            {features.map((f, i) => (
              <li key={f.label} className="animate-in" style={{ animationDelay: `${i * 120 + 220}ms` }}>
                <span className="auth-content-feature-icon">{f.icon}</span>
                {f.label}
              </li>
            ))}
          </ul>
        )}

        {stat && (
          <div className="auth-content-stat animate-in" style={{ animationDelay: "620ms" }}>
            <span className="auth-content-stat-dot" />
            {stat}
          </div>
        )}
      </div>
    </div>
  );
}
