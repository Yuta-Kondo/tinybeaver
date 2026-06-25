import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Message } from "../hooks/useChat";
import MapCard from "./MapCard";

interface Props {
  message: Message;
  sessionId: string | null;
  onResend: (msgId: number, newContent: string) => void;
  onDelete: (msgId: number) => void;
}

function StatusLine({ status }: { status: "searching" | "memory_updating" | "reading_email" }) {
  const label = status === "searching" ? "Searching the web…"
    : status === "reading_email" ? "Reading emails…"
    : "Saving to memory…";
  return (
    <div className="status-line">
      <span className="status-dot" />
      {label}
    </div>
  );
}

function TopicTag({ slug, variant }: { slug: string; variant: "loaded" | "updated" }) {
  return (
    <span className={`topic-tag topic-tag--${variant}`} title={variant === "loaded" ? "Context loaded" : "Memory updated"}>
      {variant === "updated" && "✦ "}
      {slug}
    </span>
  );
}

function modelLabel(id: string): string {
  if (id.includes("opus")) return "Opus";
  if (id.includes("sonnet")) return "Sonnet";
  if (id.includes("haiku")) return "Haiku";
  if (id.includes("fable")) return "Fable";
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

export default function MessageBubble({ message, sessionId, onResend, onDelete }: Props) {
  const { id, role, content, images, streaming, status, newTopic, loadedTopics, updatedTopics, fetchedUrls, model, costUsd, costBreakdown, locations, searchSources } = message;

  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(content);
  const [hovered, setHovered] = useState(false);

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
      className={`message-row ${role}`}
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
              <img key={i} src={src} alt={`image ${i + 1}`} className="message-image" />
            ))}
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
                <button className="edit-submit-btn" onClick={submitEdit}>Resend ↑</button>
                <button className="edit-cancel-btn" onClick={cancelEdit}>Cancel</button>
              </div>
            </div>
          ) : (
            <div className="user-text">{renderUserContent(content)}</div>
          )
        ) : (
          <>
            {(status === "searching" || status === "reading_email") && !content && <StatusLine status={status} />}
            {content && (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={{
                  table: ({ children }) => (
                    <div className="table-wrap"><table>{children}</table></div>
                  ),
                }}
              >
                {content}
              </ReactMarkdown>
            )}
            {streaming && !status && <span className="cursor" />}
            {streaming && !content && !status && <span className="cursor" />}
            {status === "memory_updating" && <StatusLine status="memory_updating" />}
            {(status === "searching" || status === "reading_email") && content && <StatusLine status={status} />}
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
              <div className="map-cards">
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

      {/* Hover actions */}
      {hovered && !streaming && id && !editing && (
        <div className={`msg-actions msg-actions--${role}`}>
          {role === "user" && (
            <>
              <button className="msg-action-btn" onClick={() => onResend(id, content)} title="Retry">↺</button>
              <button className="msg-action-btn" onClick={startEdit} title="Edit & resend">✎</button>
            </>
          )}
          <button
            className="msg-action-btn msg-action-btn--delete"
            onClick={() => onDelete(id)}
            title="Delete message"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
