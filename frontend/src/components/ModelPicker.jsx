export const MODEL_OPTIONS = [
  { value: "haiku", label: "Haiku" },
  { value: "sonnet", label: "Sonnet" },
  { value: "opus", label: "Opus" },
];

// Sits directly above the chat input, same placement convention as claude.ai's
// own model switcher. Only ever picks which Claude model is tried first - if
// Claude fails, the backend falls back to Gemini regardless of this choice.
export default function ModelPicker({ value, onChange, disabled }) {
  return (
    <div className="model-picker">
      <span className="model-picker-icon">✦</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {MODEL_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
