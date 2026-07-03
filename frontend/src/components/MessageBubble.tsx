import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Message } from "../hooks/useChat";
import hljs from "highlight.js/lib/common";
import { fetchTopic, sendFeedback } from "../lib/api";
import Icon from "./Icon";
import MapCard from "./MapCard";

interface Props {
  message: Message;
  sessionId: string | null;
  onResend: (msgId: number, newContent: string) => void;
  onRegenerate?: () => void;
  onRetry?: () => void;
  onContinue?: () => void;
  onDelete: (msgId: number) => void;
}

// Touch devices have no hover, so hover-gated actions never appear.
// On coarse pointers we always render the action row instead.
const IS_COARSE_POINTER =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(pointer: coarse)").matches;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);
  return (
    <button className="msg-action-btn" onClick={copy} title="Copy">
      <Icon name={copied ? "check" : "copy"} />
    </button>
  );
}

function FeedbackButtons({ text }: { text: string }) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");

  function vote(r: "up" | "down") {
    setRating(r);
    sendFeedback(r, text).catch(() => {});
    if (r === "down") setNoteOpen(true);
  }
  function submitNote() {
    if (note.trim()) sendFeedback("down", text, note.trim()).catch(() => {});
    setNoteOpen(false);
  }

  return (
    <>
      <button
        className={`msg-action-btn${rating === "up" ? " msg-action-btn--on" : ""}`}
        onClick={() => vote("up")}
        title="Good response"
      ><Icon name="thumbUp" /></button>
      <button
        className={`msg-action-btn${rating === "down" ? " msg-action-btn--on" : ""}`}
        onClick={() => vote("down")}
        title="Bad response"
      ><Icon name="thumbDown" /></button>
      {noteOpen && (
        <input
          className="feedback-note-input"
          placeholder="What went wrong? (optional)"
          value={note}
          autoFocus
          onChange={(e) => setNote(e.target.value)}
          onBlur={submitNote}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); submitNote(); }
            if (e.key === "Escape") setNoteOpen(false);
          }}
        />
      )}
    </>
  );
}

function CodeBlock({ lang, code }: { lang?: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [code]);

  // Syntax-highlight: use the tagged language if hljs knows it, else auto-detect.
  const highlighted = useMemo(() => {
    try {
      if (lang && hljs.getLanguage(lang)) {
        return { html: hljs.highlight(code, { language: lang }).value, lang };
      }
      const auto = hljs.highlightAuto(code);
      return { html: auto.value, lang: auto.language || lang };
    } catch {
      return null;
    }
  }, [code, lang]);

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-lang">{highlighted?.lang || lang || "code"}</span>
        <button className="code-block-copy" onClick={copy} title="Copy code">
          <Icon name={copied ? "check" : "copy"} size={12} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        {highlighted
          ? <code className="hljs" dangerouslySetInnerHTML={{ __html: highlighted.html }} />
          : <code>{code}</code>}
      </pre>
    </div>
  );
}

function StatusLine({ status }: { status: "searching" | "memory_updating" | "reading_email" | "moa_brainstorm" | "moa_synthesizing" }) {
  const label =
    status === "searching"       ? "Searching the web…" :
    status === "reading_email"   ? "Reading emails…" :
    status === "moa_brainstorm"  ? "Consulting 3 agents…" :
    status === "moa_synthesizing"? "Synthesizing…" :
    "Saving to memory…";
  return (
    <div className="status-line">
      <span className="status-dot" />
      {label}
    </div>
  );
}

function TopicTag({ slug, variant }: { slug: string; variant: "loaded" | "updated" }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && content === null) {
      setLoading(true);
      try {
        const t = await fetchTopic(slug);
        setContent(t.content || "_(empty)_");
      } catch {
        setContent("_Could not load this memory._");
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <span className="topic-tag-wrap">
      <button
        className={`topic-tag topic-tag--${variant} topic-tag--clickable`}
        title={variant === "loaded" ? "Context loaded — click to view" : "Memory updated — click to view"}
        onClick={toggle}
      >
        {variant === "updated" && "✦ "}
        {slug}
      </button>
      {open && (
        <div className="topic-popover">
          <div className="topic-popover-head">
            <span>{variant === "loaded" ? "Loaded into context" : "Written to memory"}: <strong>{slug}</strong></span>
            <button className="topic-popover-close" onClick={() => setOpen(false)} aria-label="Close"><Icon name="close" size={12} /></button>
          </div>
          <div className="topic-popover-body">
            {loading ? "Loading…" : content}
          </div>
        </div>
      )}
    </span>
  );
}

function modelLabel(id: string): string {
  if (id === "moa") return "Multi";
  if (id.includes("opus")) return "Opus";
  if (id.includes("sonnet")) return "Sonnet";
  if (id.includes("haiku")) return "Haiku";
  if (id.includes("fable")) return "Fable";
  if (id.includes("flash")) return "Flash";
  return id;
}

function renderUserContent(content: string) {
  const parts = content.split(/(@[\w-]+)/g);
  return (
    <>
      {parts.map((part, i) =>
        /^@[\w-]+$/.test(part) ? (
          <span key={i} className="mention">{part}</span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

function safeHostname(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function safeFavicon(url: string): string {
  try { return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=16`; } catch { return ""; }
}

function formatCost(usd: number): string {
  if (usd < 0.00001) return "";
  if (usd < 0.0001) return "<0.01¢";
  if (usd < 0.01) return `${(usd * 100).toFixed(2)}¢`;
  return `$${usd.toFixed(4)}`;
}

const AGENT_ORDER = ["Comprehensive", "Concise", "Critical"];
const AGENT_ICON: Record<string, string> = { Comprehensive: "🔍", Concise: "⚡", Critical: "🎯" };

function MoADrafts({ drafts, streaming }: { drafts: { persona: string; text: string; done?: boolean }[]; streaming: boolean }) {
  const [open, setOpen] = useState(true);
  const userToggled = useRef(false);

  useEffect(() => {
    if (!streaming && !userToggled.current) setOpen(false);
  }, [streaming]);

  function handleToggle() {
    userToggled.current = true;
    setOpen((o) => !o);
  }

  const doneCnt = drafts.filter((d) => d.done).length;
  const currentAgent = drafts.find((d) => !d.done);
  const label = streaming && doneCnt < 3
    ? currentAgent
      ? `Agent ${doneCnt + 1}/3 · ${currentAgent.persona} writing…`
      : `Starting agent ${doneCnt + 1}/3…`
    : `Agent discussion · ${drafts.length} responses`;

  return (
    <div className="moa-drafts">
      <button className="moa-drafts-toggle" onClick={handleToggle} type="button">
        <span className={`moa-drafts-chevron${open ? " open" : ""}`}>›</span>
        <span className="moa-drafts-label">{label}</span>
      </button>
      {open && (
        <div className="moa-drafts-body">
          {AGENT_ORDER.map((name) => {
            const d = drafts.find((x) => x.persona === name);
            if (!d) {
              return streaming ? (
                <div key={name} className="moa-draft-item moa-draft-item--pending">
                  <span className="status-dot" />
                  <span className="moa-draft-pending-name">{AGENT_ICON[name]} {name} starting…</span>
                </div>
              ) : null;
            }
            return (
              <div key={name} className="moa-draft-item">
                <div className="moa-draft-persona">
                  <span>{AGENT_ICON[name] ?? "·"}</span>
                  {name}
                  {!d.done && <span className="moa-agent-streaming"> · writing…</span>}
                </div>
                <div className="moa-draft-text">
                  {d.text}
                  {!d.done && <span className="cursor" />}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function MessageBubble({ message, sessionId, onResend, onRegenerate, onRetry, onContinue, onDelete }: Props) {
  const { id, role, content, images, streaming, status, isError, stopped, newTopic, loadedTopics, updatedTopics, fetchedUrls, model, costUsd, costBreakdown, locations, searchSources, moaDrafts } = message;

  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(content);
  const [hovered, setHovered] = useState(false);
  const [lightbox, setLightbox] = useState<string | null>(null);

  function startEdit() {
    setEditDraft(content);
    setEditing(true);
  }

  function submitEdit() {
    if (!id || !editDraft.trim()) return;
    setEditing(false);
    onResend(id, editDraft.trim());
  }

  function cancelEdit() {
    setEditing(false);
    setEditDraft(content);
  }

  return (
    <div
      className={`message-row ${role}${isError ? " message-row--error" : ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="message-bubble">
        {newTopic && (
          <div className="new-topic-badge">
            ✦ New memory topic: <strong>{newTopic}</strong>
          </div>
        )}
        {images && images.length > 0 && (
          <div className="message-images">
            {images.map((src, i) => (
              <img
                key={i}
                src={src}
                alt={`image ${i + 1}`}
                className="message-image"
                onClick={() => setLightbox(src)}
              />
            ))}
          </div>
        )}
        {lightbox && (
          <div className="lightbox-backdrop" onClick={() => setLightbox(null)}>
            <img src={lightbox} alt="full size" className="lightbox-img" />
            <button className="lightbox-close" onClick={() => setLightbox(null)} aria-label="Close"><Icon name="close" /></button>
          </div>
        )}

        {role === "user" ? (
          editing ? (
            <div className="edit-area">
              <textarea
                className="edit-textarea"
                value={editDraft}
                onChange={(e) => setEditDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitEdit(); }
                  if (e.key === "Escape") cancelEdit();
                }}
                autoFocus
              />
              <div className="edit-actions">
                <button className="edit-submit-btn" onClick={submitEdit}>Resend</button>
                <button className="edit-cancel-btn" onClick={cancelEdit}>Cancel</button>
              </div>
            </div>
          ) : (
            <div className="user-text">{renderUserContent(content)}</div>
          )
        ) : isError ? (
          <div className="error-bubble">
            <span className="error-bubble-icon" aria-hidden="true">⚠</span>
            <span className="error-bubble-text">{content}</span>
            {onRetry && (
              <button className="error-retry-btn" onClick={onRetry}>Retry</button>
            )}
          </div>
        ) : (
          <>
            {moaDrafts && moaDrafts.length > 0 && (
              <MoADrafts drafts={moaDrafts} streaming={!!streaming} />
            )}
            {(status === "searching" || status === "reading_email" || status === "moa_synthesizing") && !content && <StatusLine status={status} />}
            {status === "moa_brainstorm" && (!moaDrafts || moaDrafts.length === 0) && !content && <StatusLine status={status} />}
            {content && (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{
                  table: ({ children }) => (
                    <div className="table-wrap"><table>{children}</table></div>
                  ),
                  code({ className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || "");
                    const raw = String(children);
                    const isBlock = !!match || raw.includes("\n");
                    if (!isBlock) {
                      return <code className={className} {...props}>{children}</code>;
                    }
                    return <CodeBlock lang={match?.[1]} code={raw.replace(/\n$/, "")} />;
                  },
                  pre: ({ children }) => <>{children}</>,
                }}
              >
                {content}
              </ReactMarkdown>
            )}
            {streaming && !status && <span className="cursor" />}
            {streaming && !content && !status && <span className="cursor" />}
            {stopped && (
              <span className="stopped-label">
                <Icon name="stop" size={9} /> Stopped
                {onContinue && (
                  <button className="continue-btn" onClick={onContinue}>Continue</button>
                )}
              </span>
            )}
            {status === "memory_updating" && <StatusLine status="memory_updating" />}
            {(status === "searching" || status === "reading_email" || status === "moa_synthesizing") && content && <StatusLine status={status} />}
            {!streaming && searchSources && searchSources.length > 0 && (
              <div className="search-sources">
                <div className="search-sources-label">References</div>
                {searchSources.map((s) => (
                  <a key={s.n} className="search-source-item" href={s.url} target="_blank" rel="noopener noreferrer">
                    <span className="search-source-n">[{s.n}]</span>
                    {safeFavicon(s.url) && (
                      <span className="search-source-favicon">
                        <img src={safeFavicon(s.url)} alt="" width={14} height={14} />
                      </span>
                    )}
                    <span className="search-source-title">{s.title}</span>
                    <span className="search-source-domain">{safeHostname(s.url)}</span>
                  </a>
                ))}
              </div>
            )}
            {!streaming && locations && locations.length > 0 && (
              <div className="map-chips">
                {locations.map((loc, i) => <MapCard key={i} location={loc} />)}
              </div>
            )}
          </>
        )}

        {/* Metadata row */}
        {(model || fetchedUrls?.length || loadedTopics?.length || updatedTopics?.length || costUsd) ? (
          <div className="topic-meta">
            {model && !streaming && (
              <span className="topic-tag topic-tag--model" title="Model used">{modelLabel(model)}</span>
            )}
            {costUsd != null && !streaming && formatCost(costUsd) && (
              <span
                className="topic-tag topic-tag--cost"
                title={costBreakdown
                  ? `Chat: ${formatCost(costBreakdown.chat)} · Memory: ${formatCost(costBreakdown.memory)}`
                  : "API cost estimate"}
              >
                {formatCost(costUsd)}
              </span>
            )}
            {fetchedUrls?.map((u) => {
              try {
                return <span key={u} className="topic-tag topic-tag--url" title={u}>⬆ {new URL(u).hostname}</span>;
              } catch {
                return null;
              }
            })}
            {loadedTopics?.map((t) => <TopicTag key={`l-${t}`} slug={t} variant="loaded" />)}
            {updatedTopics?.map((t) => <TopicTag key={`u-${t}`} slug={t} variant="updated" />)}
          </div>
        ) : null}
      </div>

      {/* Hover actions (always visible on touch — no hover there) */}
      {(hovered || IS_COARSE_POINTER) && !streaming && id && !editing && (
        <div className={`msg-actions msg-actions--${role}`}>
          {role === "user" && (
            <>
              <button className="msg-action-btn" onClick={() => onResend(id, content)} title="Retry"><Icon name="regenerate" /></button>
              <button className="msg-action-btn" onClick={startEdit} title="Edit & resend"><Icon name="edit" /></button>
            </>
          )}
          {role === "assistant" && onRegenerate && (
            <button className="msg-action-btn" onClick={onRegenerate} title="Regenerate"><Icon name="regenerate" /></button>
          )}
          {role === "assistant" && <FeedbackButtons text={content} />}
          <CopyButton text={content} />
          <button
            className="msg-action-btn msg-action-btn--delete"
            onClick={() => onDelete(id)}
            title="Delete message"
          >
            <Icon name="trash" />
          </button>
        </div>
      )}
    </div>
  );
}
