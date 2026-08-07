import { useState, useCallback, useMemo } from "react";
import { useEscapeKey } from "../hooks/useEscapeKey";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Message } from "../hooks/useChat";
import hljs from "highlight.js/lib/common";
import { fetchTopic, sendFeedback } from "../lib/api";
import { MOA_AGENTS, MOA_SYNTHESIS_MODEL, moaAgentModel, moaPipelineLabel, modelLabel, modelShortLabel } from "../lib/models";
import Icon from "./Icon";
import MapCard from "./MapCard";
import MessageAttachments from "./MessageAttachments";
import { TypingIndicator, WaitingIndicator, WAIT_LABELS } from "./WaitingIndicator";

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
    status === "searching"        ? WAIT_LABELS.searching :
    status === "reading_email"    ? WAIT_LABELS.readingEmail :
    status === "moa_brainstorm"   ? WAIT_LABELS.moaBrainstorm :
    status === "moa_synthesizing" ? WAIT_LABELS.moaSynthesize :
    WAIT_LABELS.memory;
  return <WaitingIndicator label={label} size="md" className="status-line" />;
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
            {loading ? <WaitingIndicator label={WAIT_LABELS.topic} size="sm" /> : content}
          </div>
        </div>
      )}
    </span>
  );
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

const AGENT_ORDER: string[] = MOA_AGENTS.map((a) => a.persona);
const AGENT_COUNT = MOA_AGENTS.length;

type MoADraft = { persona: string; text: string; model?: string; done?: boolean; confidence?: number };

function draftModelLabel(draft: { persona: string; model?: string }): string {
  const id = draft.model || moaAgentModel(draft.persona);
  return id ? modelShortLabel(id) : "";
}

/** Confidence rendered as a meter — comparable across columns at a glance,
 *  which a bare percentage never was. Absent when the model dropped the
 *  `Confidence:` footer (small models do this often; see moa-research-memo). */
function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <span
      className="moa-confidence"
      title={`Self-reported confidence: ${pct}% (not calibrated)`}
    >
      <span className="moa-confidence-track">
        <span className="moa-confidence-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="moa-confidence-value">{pct}%</span>
    </span>
  );
}

function MoADrafts({
  drafts,
  streaming,
  synthesizing,
}: {
  drafts: MoADraft[];
  streaming: boolean;
  synthesizing?: boolean;
}) {
  // Stays open once finished: the drafts are the evidence for the synthesis
  // below them, so hiding them the moment they matter defeats the mode.
  const [open, setOpen] = useState(true);

  const doneCnt = drafts.filter((d) => d.done).length;
  const writingCnt = drafts.filter((d) => !d.done && d.text).length;
  const proposing = streaming && !synthesizing && doneCnt < AGENT_COUNT;
  const finished = !streaming && doneCnt > 0;

  let phaseLabel: string;
  if (synthesizing && streaming) {
    phaseLabel = "Merging three views…";
  } else if (streaming) {
    phaseLabel = proposing && writingCnt > 0 ? "Three agents are drafting…" : "Starting three agents…";
  } else {
    phaseLabel = "Discussion";
  }

  return (
    <div className={`moa-drafts${streaming ? " moa-drafts--live" : ""}`}>
      <button
        className="moa-drafts-toggle"
        onClick={() => setOpen((o) => !o)}
        type="button"
        aria-expanded={open}
      >
        <span className={`moa-drafts-chevron${open ? " open" : ""}`}>›</span>
        <span className="moa-drafts-label">{phaseLabel}</span>
        <span className="moa-progress" aria-hidden="true">
          {AGENT_ORDER.map((name) => {
            const d = drafts.find((x) => x.persona === name);
            const state = d?.done ? "done" : d?.text ? "writing" : "idle";
            return (
              <span
                key={name}
                className={`moa-progress-dot moa-role--${name.toLowerCase()}${
                  state === "idle" ? "" : ` moa-progress-dot--${state}`
                }`}
              />
            );
          })}
        </span>
        {proposing && writingCnt > 0 && (
          <span className="moa-drafts-phase">live</span>
        )}
        {synthesizing && streaming && (
          <span className="moa-drafts-phase moa-drafts-phase--synth">merge</span>
        )}
      </button>
      {open && (
        <div className="moa-drafts-grid">
          {AGENT_ORDER.map((name) => {
            const d = drafts.find((x) => x.persona === name);
            const roleClass = `moa-role--${name.toLowerCase()}`;
            if (!d) {
              if (!streaming) return null;
              return (
                <div key={name} className={`moa-draft-card moa-draft-card--pending ${roleClass}`}>
                  <div className="moa-draft-card-head">
                    <span className="moa-draft-role">{name}</span>
                    <span className="moa-draft-status">waiting</span>
                  </div>
                  <div className="moa-draft-card-body moa-draft-card-body--empty">
                    <span className="status-dot" />
                    Starting…
                  </div>
                </div>
              );
            }
            const status = d.done ? "done" : d.text ? "writing" : "waiting";
            return (
              <div
                key={name}
                className={`moa-draft-card ${roleClass}${d.done ? " moa-draft-card--done" : ""}${!d.done && d.text ? " moa-draft-card--writing" : ""}`}
              >
                <div className="moa-draft-card-head">
                  <span className="moa-draft-role">{name}</span>
                  <div className="moa-draft-card-meta">
                    {d.confidence != null && !Number.isNaN(d.confidence) ? (
                      <ConfidenceMeter value={d.confidence} />
                    ) : d.done ? (
                      <span className="moa-draft-status" title="This agent did not report a confidence score">
                        no score
                      </span>
                    ) : null}
                    {status === "writing" && (
                      <WaitingIndicator label="" size="sm" className="moa-agent-streaming" />
                    )}
                  </div>
                </div>
                <div className="moa-draft-card-body">
                  {d.text || (streaming ? "" : "—")}
                  {!d.done && d.text && <span className="cursor" />}
                </div>
              </div>
            );
          })}
          {/* Legacy personas (e.g. Minimalist) from older MoA runs */}
          {drafts
            .filter((d) => !AGENT_ORDER.includes(d.persona))
            .map((d) => (
                <div key={d.persona} className="moa-draft-card moa-draft-card--done">
                  <div className="moa-draft-card-head">
                    <span className="moa-draft-role">{d.persona}</span>
                    <div className="moa-draft-card-meta">
                      {d.confidence != null && !Number.isNaN(d.confidence) && (
                        <ConfidenceMeter value={d.confidence} />
                      )}
                      {draftModelLabel(d) && (
                        <span className="moa-draft-model">{draftModelLabel(d)}</span>
                      )}
                    </div>
                  </div>
                  <div className="moa-draft-card-body">{d.text}</div>
                </div>
            ))}
        </div>
      )}
      {open && finished && (
        <div className="moa-synthesis-seam">
          <span className="moa-synthesis-seam-line" aria-hidden="true" />
          <span>synthesized below · weighted by confidence</span>
          <span className="moa-synthesis-seam-line" aria-hidden="true" />
        </div>
      )}
    </div>
  );
}

export default function MessageBubble({ message, sessionId, onResend, onRegenerate, onRetry, onContinue, onDelete }: Props) {
  const { id, role, content, images, attachments, streaming, status, isError, stopped, newTopic, loadedTopics, updatedTopics, fetchedUrls, model, costUsd, costBreakdown, locations, searchSources, moaDrafts } = message;

  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(content);
  const [hovered, setHovered] = useState(false);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const closeLightbox = useCallback(() => setLightbox(null), []);
  useEscapeKey(lightbox != null, closeLightbox);

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
        {attachments && attachments.length > 0 && (
          <MessageAttachments attachments={attachments} />
        )}
        {images && images.length > 0 && !attachments?.length && (
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
          <div
            className="lightbox-backdrop"
            onClick={closeLightbox}
            role="dialog"
            aria-modal="true"
            aria-label="Image preview"
          >
            <img src={lightbox} alt="full size" className="lightbox-img" />
            <button className="lightbox-close" onClick={closeLightbox} aria-label="Close"><Icon name="close" /></button>
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
          ) : content ? (
            <div className="user-text">{renderUserContent(content)}</div>
          ) : null
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
              <MoADrafts
                drafts={moaDrafts}
                streaming={!!streaming}
                synthesizing={status === "moa_synthesizing"}
              />
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
            {streaming && !content && !status && <TypingIndicator />}
            {streaming && content && !status && <span className="cursor" aria-hidden="true" />}
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
              <span
                className="topic-tag topic-tag--model"
                title={model === "moa" ? moaPipelineLabel() : "Model used"}
              >
                {model === "moa"
                  ? `Self-MoA → ${modelShortLabel(MOA_SYNTHESIS_MODEL)}`
                  : modelLabel(model)}
              </span>
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
