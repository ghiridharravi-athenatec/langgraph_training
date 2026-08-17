import { useEffect, useState } from "react";

// Cycles through a caller-supplied list of status phrases while a response is
// pending - the same "shimmering status line" pattern claude.ai uses. This is
// purely cosmetic: /chat and /database/chat are single blocking requests, not
// a stream, so the phrases don't reflect the pipeline's real current stage -
// they just give the wait some texture instead of a bare set of dots.
const CYCLE_MS = 1800;

export default function ThinkingIndicator({ messages }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % messages.length);
    }, CYCLE_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length]);

  return (
    <div className="chat-message chat-message-assistant">
      <div className="chat-bubble chat-bubble-thinking">
        <span className="thinking-dot" />
        <span key={index} className="thinking-text">
          {messages[index]}
        </span>
      </div>
    </div>
  );
}
