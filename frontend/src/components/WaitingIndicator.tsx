/** Shared loading / waiting UI used across chat, panels, and attachments. */

type Size = "sm" | "md";

interface WaitingProps {
  label?: string;
  size?: Size;
  className?: string;
}

export function Spinner({ size = "md" }: { size?: Size }) {
  return <span className={`wait-spinner wait-spinner--${size}`} aria-hidden="true" />;
}

export function WaitingDots({ size = "md" }: { size?: Size }) {
  return (
    <span className={`wait-dots wait-dots--${size}`} aria-hidden="true">
      <span /><span /><span />
    </span>
  );
}

/** Inline spinner + label — status lines, file chips, popovers. */
export function WaitingIndicator({ label, size = "md", className = "" }: WaitingProps) {
  return (
    <span className={`wait-indicator wait-indicator--${size} ${className}`.trim()} role="status">
      <Spinner size={size} />
      {label && <span className="wait-label">{label}</span>}
    </span>
  );
}

/** Centered block loader for panels (Gmail, empty regions). */
export function WaitingBlock({ label = "Loading…", className = "" }: { label?: string; className?: string }) {
  return (
    <div className={`wait-block ${className}`.trim()} role="status" aria-live="polite">
      <Spinner size="md" />
      <span className="wait-label">{label}</span>
    </div>
  );
}

/** Assistant is generating but no text yet. */
export function TypingIndicator({ label = "Thinking…" }: { label?: string }) {
  return (
    <div className="typing-indicator" role="status" aria-live="polite">
      <WaitingDots size="md" />
      <span className="wait-label">{label}</span>
    </div>
  );
}

/** Session history loading — chat-shaped skeleton bubbles. */
export function ChatSessionSkeleton() {
  return (
    <div className="session-skeleton" aria-label="Loading conversation" aria-busy="true">
      <div className="skeleton-bubble skeleton-bubble--user" style={{ width: "42%" }} />
      <div className="skeleton-bubble skeleton-bubble--assistant">
        <div className="skeleton-line" style={{ width: "88%" }} />
        <div className="skeleton-line" style={{ width: "72%" }} />
        <div className="skeleton-line" style={{ width: "54%" }} />
      </div>
      <div className="skeleton-bubble skeleton-bubble--user" style={{ width: "34%" }} />
      <div className="skeleton-bubble skeleton-bubble--assistant">
        <div className="skeleton-line" style={{ width: "80%" }} />
        <div className="skeleton-line" style={{ width: "64%" }} />
      </div>
    </div>
  );
}

export const WAIT_LABELS = {
  thinking: "Thinking…",
  searching: "Searching the web…",
  readingEmail: "Reading emails…",
  memory: "Saving to memory…",
  moaBrainstorm: "Consulting 3 agents…",
  moaSynthesize: "Synthesizing answer…",
  fileRead: "Reading with Flash…",
  session: "Loading conversation…",
  topic: "Loading memory…",
  gmail: "Loading inbox…",
  gmailOpen: "Opening email…",
} as const;
