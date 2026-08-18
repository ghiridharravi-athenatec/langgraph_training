// The database agent's guardrail_events are one db_agent_tool_call entry per
// tool invocation (which table it listed, what query it ran) - a different
// shape from the document pipeline's fixed guardrail checklist, so this
// renders them directly rather than trying to fit them into GuardrailPanel's
// checklist view. Shared between the live Database Agent chat screen and
// the Guardrails Observability trace detail view.
export default function ToolCallLog({ events }) {
  const toolCalls = (events || []).filter((e) => e.stage === "db_agent_tool_call");
  if (toolCalls.length === 0) return null;
  return (
    <details className="chat-raw-logs db-tool-log">
      <summary>{toolCalls.length} tool call{toolCalls.length === 1 ? "" : "s"}</summary>
      {toolCalls.map((e, i) => (
        <div key={i} className="chat-log-line">
          <span className={`guardrail-badge ${e.passed ? "guardrail-badge-pii" : "guardrail-badge-warn"}`}>
            {e.passed ? "✓" : "✗"} {e.tool}
          </span>
          {e.reason && <span> — {e.reason}</span>}
        </div>
      ))}
    </details>
  );
}
