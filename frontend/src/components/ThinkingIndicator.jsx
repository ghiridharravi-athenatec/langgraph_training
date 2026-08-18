import { useEffect, useState } from "react";

// Cycles through a caller-supplied list of status phrases while a response is
// pending - the same "shimmering status line" pattern claude.ai uses. This is
// a fallback only: when liveStage is supplied (the pipeline's real current
// stage, polled from GET /progress/{request_id} - see app/core/progress.py),
// that text is shown verbatim instead, with no cycling - it already reflects
// what's actually happening. Cycling only kicks in before the first live
// stage arrives, or if the caller never passes one at all.
const CYCLE_MS = 1800;

export default function ThinkingIndicator({ messages, liveStage }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (liveStage) return; // real progress is driving the text - no need to cycle
    setIndex(0);
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % messages.length);
    }, CYCLE_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, !!liveStage]);

  const text = liveStage || messages[index];

  return (
    <div className="chat-message chat-message-assistant">
      <div className="chat-bubble chat-bubble-thinking">
        <span className="thinking-dot" />
        <span key={text} className="thinking-text">
          {text}
        </span>
      </div>
    </div>
  );
}
