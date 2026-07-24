import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";
import BeaverLoader from "./BeaverLoader";
import { fileIcon } from "../lib/attachments";

export interface DocItem {
  id?: number;
  key: string;
  name: string;
  kind: "image" | "pdf" | "file";
  size_kb?: number;
  chars?: number;
  status?: "processing" | "ready" | "failed" | "pending";
  error?: string;
  loading?: boolean;
}

interface Props {
  documents: DocItem[];
  onAddClick: () => void;
  onRemove: (id: number) => void;
  disabled?: boolean;
}

const MENU_W = 300;

/** Top-bar control listing documents attached to the whole chat session. */
export default function DocumentsPanel({ documents, onAddClick, onRemove, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const count = documents.length;
  const busy = documents.some(
    (d) => d.loading || d.status === "processing" || d.status === "pending"
  );

  const reposition = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    // Keep the panel within the chat content area (right of the sidebar) so it
    // never covers the sidebar; fall back to the viewport if not found.
    const area = btn.closest(".chat-area")?.getBoundingClientRect();
    const boundLeft = (area?.left ?? 0) + 8;
    const boundRight = (area?.right ?? window.innerWidth) - 8;
    const width = Math.min(MENU_W, boundRight - boundLeft);
    const desired = r.right - width; // right-aligned to the button
    const left = Math.min(Math.max(boundLeft, desired), boundRight - width);
    setPos({ top: r.bottom + 6, left, width });
  }, []);

  // Position the portal menu the moment it opens, before paint.
  useLayoutEffect(() => {
    if (open) reposition();
  }, [open, reposition]);

  // Close on outside click; reposition on resize/scroll so it tracks the button.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onReflow() {
      reposition();
    }
    document.addEventListener("mousedown", onDown);
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
  }, [open, reposition]);

  return (
    <div className="docs-panel">
      <button
        ref={btnRef}
        className={`docs-btn${count > 0 ? " docs-btn--active" : ""}`}
        onClick={() => setOpen((o) => !o)}
        type="button"
        title="Documents in this chat"
      >
        {busy ? (
          <BeaverLoader size="sm" />
        ) : (
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13" aria-hidden="true">
            <path d="M4 1.5h5l3 3v10a.5.5 0 01-.5.5H4a.5.5 0 01-.5-.5v-12A.5.5 0 014 1.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
            <path d="M9 1.5V4.5H12" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
          </svg>
        )}
        Docs
        {count > 0 && <span className="docs-btn-count">{count}</span>}
      </button>

      {open && pos &&
        createPortal(
          <div
            ref={menuRef}
            className="docs-menu"
            style={{ top: pos.top, left: pos.left, width: pos.width }}
          >
            <div className="docs-menu-header">
              <span>Documents in this chat</span>
              <button
                className="docs-add-btn"
                onClick={() => { onAddClick(); }}
                type="button"
                disabled={disabled}
                title="Add document"
              >
                <Icon name="attach" size={13} /> Add
              </button>
            </div>

            {count === 0 ? (
              <div className="docs-empty">
                No documents yet. Add files and the assistant will refer to them throughout this conversation.
              </div>
            ) : (
              <div className="docs-list">
                {documents.map((d) => (
                  <div key={d.key} className="docs-item">
                    <span className="docs-item-icon">{fileIcon(d.name)}</span>
                    <div className="docs-item-info">
                      <span className="docs-item-name" title={d.name}>{d.name}</span>
                      <span className="docs-item-meta">
                        {d.loading
                          ? "Uploading…"
                          : d.status === "processing" || d.status === "pending"
                          ? (d.error || "Indexing…")
                          : d.status === "failed"
                          ? (d.error ? `Failed: ${d.error}` : "Failed")
                          : d.chars && d.chars > 0
                          ? `${d.size_kb != null && d.size_kb > 0 ? `${d.size_kb} KB · ` : ""}${(d.chars / 1000).toFixed(0)}k chars`
                          : d.size_kb != null && d.size_kb > 0
                          ? `${d.size_kb} KB`
                          : d.kind}
                      </span>
                    </div>
                    {d.loading || d.status === "processing" || d.status === "pending" ? (
                      <BeaverLoader size="sm" />
                    ) : (
                      <button
                        className="docs-item-remove"
                        onClick={() => d.id != null && onRemove(d.id)}
                        title="Remove document"
                      >
                        <Icon name="close" size={11} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>,
          document.body
        )}
    </div>
  );
}
