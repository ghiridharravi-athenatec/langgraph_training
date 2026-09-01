import { useState } from "react";

// Shared clipboard-copy button - same navigator.clipboard.writeText + transient
// "Copied" feedback pattern already used by Instructions.jsx's ScenarioCard, reused
// here for every chat question/answer instead of a second, separately-written copy.
export default function CopyButton({ text, label = "Copy answer" }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy(e) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable (e.g. insecure context) - nothing to fall back to.
    }
  }

  return (
    <button
      type="button"
      className={`chat-copy-btn ${copied ? "chat-copy-btn-copied" : ""}`}
      onClick={handleCopy}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
    >
      <span aria-hidden="true">{copied ? "✓" : "⧉"}</span>
    </button>
  );
}
