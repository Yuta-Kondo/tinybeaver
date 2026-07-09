import { useEffect, useImperativeHandle, useRef, useState, forwardRef, useCallback } from "react";
import MessageBubble from "./MessageBubble";
import Icon from "./Icon";
import type { Message } from "../hooks/useChat";
import type { AttachedFile } from "../lib/api";
import { extractFile, fetchTopics } from "../lib/api";
import { fileIcon, ATTACHMENT_THUMB_PX } from "../lib/attachments";
import { renderPdfThumbnail } from "../lib/pdfThumb";
import { MODELS, findModel, moaPipelineLabel } from "../lib/models";

interface PendingFile extends AttachedFile {
  key: string;
  sizeKb: number;
  costUsd?: number;
  loading?: boolean;
  thumb?: string;  // first-page preview for PDFs
}

function ModelDropdown({ model, onModelChange, disabled }: { model: string; onModelChange: (m: string) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = findModel(model);

  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, close]);

  return (
    <div className="model-dropdown" ref={ref}>
      <button
        className="model-dropdown-btn"
        onClick={() => !disabled && setOpen((o) => !o)}
        type="button"
        disabled={disabled}
      >
        <span className={`model-dropdown-dot model-dropdown-dot--${active.provider}`} />
        <span className="model-dropdown-name">{active.name}</span>
        <span className="model-dropdown-version">{active.version}</span>
        <svg className={`model-dropdown-chevron${open ? " open" : ""}`} viewBox="0 0 10 6" fill="none">
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {open && (
        <div className="model-dropdown-menu">
          {MODELS.map((m) => (
            <button
              key={m.id}
              className={`model-option${model === m.id ? " model-option--active" : ""}`}
              onClick={() => { onModelChange(m.id); setOpen(false); }}
              type="button"
            >
              <span className={`model-dropdown-dot model-dropdown-dot--${m.provider}`} />
              <span className="model-option-body">
                <span className="model-option-title">
                  {m.name} <span className="model-option-version">{m.version}</span>
                </span>
                <span className="model-option-desc">{m.desc}</span>
              </span>
              {model === m.id && <span className="model-option-check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface Props {
  messages: Message[];
  streaming: boolean;
  loadingSession: boolean;
  sessionId: string | null;
  onSend: (text: string, images: string[], files: AttachedFile[]) => void;
  onCancel: () => void;
  onResend: (msgId: number, newContent: string) => void;
  onRetry: () => void;
  onContinue: (msgId: number) => void;
  onDeleteMessage: (msgId: number) => Promise<void>;
  onMenuOpen: () => void;
  model: string;
  onModelChange: (m: string) => void;
  multiAgent: boolean;
  onMultiAgentChange: (v: boolean) => void;
  privateMode: boolean;
  privateLocked: boolean;
  onPrivateModeChange: (v: boolean) => void;
}

export interface ChatViewHandle {
  focusInput: () => void;
  setDraft: (text: string) => void;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target?.result as string ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function resizeImage(file: File, maxPx: number, quality: number): Promise<string> {
  return new Promise((resolve) => {
    const fallback = () => readAsDataUrl(file).then(resolve).catch(() => resolve(""));
    const objectUrl = URL.createObjectURL(file);
    const img = new Image();
    // Timeout in case img never fires on iOS
    const timer = setTimeout(() => { URL.revokeObjectURL(objectUrl); fallback(); }, 8000);
    img.onload = () => {
      clearTimeout(timer);
      URL.revokeObjectURL(objectUrl);
      try {
        const scale = Math.min(1, maxPx / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext("2d");
        if (!ctx) { fallback(); return; }
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", quality));
      } catch {
        fallback();
      }
    };
    img.onerror = () => { clearTimeout(timer); URL.revokeObjectURL(objectUrl); fallback(); };
    img.src = objectUrl;
  });
}

const draftKey = (sid: string | null) => `draft:${sid ?? "new"}`;

// Web Speech API (Chrome/Safari expose webkit-prefixed). Undefined elsewhere.
const SpeechRecognitionImpl: any =
  typeof window !== "undefined"
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined;

const ChatView = forwardRef<ChatViewHandle, Props>(function ChatView({ messages, streaming, loadingSession, sessionId, onSend, onCancel, onResend, onRetry, onContinue, onDeleteMessage, onMenuOpen, model, onModelChange, multiAgent, onMultiAgentChange, privateMode, privateLocked, onPrivateModeChange }, ref) {
  const [draft, setDraft] = useState(() => {
    try { return localStorage.getItem(draftKey(sessionId)) ?? ""; } catch { return ""; }
  });
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [listening, setListening] = useState(false);
  const [pdfPreview, setPdfPreview] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pinnedRef = useRef(true);
  const [topicSlugs, setTopicSlugs] = useState<string[]>([]);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");

  useEffect(() => {
    fetchTopics()
      .then((topics) => setTopicSlugs(topics.map((t) => t.slug)))
      .catch(() => {});
  }, []);

  useImperativeHandle(ref, () => ({
    focusInput: () => textareaRef.current?.focus(),
    setDraft: (text: string) => {
      setDraft(text);
      setTimeout(() => textareaRef.current?.focus(), 50);
    },
  }));

  const isMobile = () => window.matchMedia("(pointer: coarse)").matches;

  // On mobile, start textarea as readOnly so iOS doesn't misplace the caret on first tap.
  // touchstart removes readOnly and focuses synchronously (within user gesture) so
  // the keyboard opens once with the correct caret position — no cursor-outside-box glitch.
  useEffect(() => {
    const el = textareaRef.current;
    if (el && isMobile()) el.readOnly = true;
  }, []);

  // Auto-focus textarea on desktop only — mobile keyboard opens on tap, not programmatically
  useEffect(() => {
    if (!streaming && !isMobile()) {
      setTimeout(() => textareaRef.current?.focus(), 80);
    }
  }, [sessionId]);

  useEffect(() => {
    if (messages.length === 0) {
      pinnedRef.current = true;
      if (!isMobile()) setTimeout(() => textareaRef.current?.focus(), 80);
    }
  }, [messages.length === 0]);

  // Restore the saved draft when switching sessions (private mode is never persisted).
  useEffect(() => {
    if (privateMode) return;
    try { setDraft(localStorage.getItem(draftKey(sessionId)) ?? ""); } catch { setDraft(""); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Persist the draft as it changes (skip private mode — nothing leaves memory).
  useEffect(() => {
    if (privateMode) return;
    try {
      if (draft) localStorage.setItem(draftKey(sessionId), draft);
      else localStorage.removeItem(draftKey(sessionId));
    } catch { /* ignore quota errors */ }
  }, [draft, sessionId, privateMode]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    pinnedRef.current = atBottom;
    setShowScrollBtn(!atBottom && el.scrollHeight - el.clientHeight > 200);
  }

  useEffect(() => {
    if (pinnedRef.current) {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  function snapToBottom() {
    pinnedRef.current = true;
    setShowScrollBtn(false);
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  // ── File handling (all types → LLM extraction via /files/extract) ──

  async function processFile(file: File) {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const isImage = file.type.startsWith("image/") || ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tiff"].includes(ext);

    const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    let thumb: string | undefined;
    if (isImage) {
      try {
        thumb = await resizeImage(file, ATTACHMENT_THUMB_PX, 0.8);
      } catch {
        /* preview optional */
      }
    }

    const placeholder: PendingFile = { key, name: file.name, text: "", sizeKb: 0, loading: true, thumb };
    setPendingFiles((p) => [...p, placeholder]);

    if (ext === "pdf") {
      renderPdfThumbnail(file).then((pdfThumb) => {
        if (pdfThumb) {
          setPendingFiles((p) => p.map((f) => (f.key === key ? { ...f, thumb: pdfThumb } : f)));
        }
      });
    }

    try {
      const result = await extractFile(file);
      setPendingFiles((p) =>
        p.map((f) =>
          f.key === key
            ? { ...f, name: result.filename, text: result.text, sizeKb: result.size_kb, costUsd: result.cost_usd, loading: false }
            : f
        )
      );
    } catch (e: any) {
      setPendingFiles((p) => p.filter((f) => f.key !== key));
      alert(`Could not read "${file.name}": ${e.message}`);
    }
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    Array.from(e.target.files ?? []).forEach(processFile);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    Array.from(e.dataTransfer.files).forEach(processFile);
  }

  function removeFile(idx: number) {
    setPendingFiles((p) => p.filter((_, i) => i !== idx));
  }

  // ── Paste ──────────────────────────────────────────

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter((item) => item.type.startsWith("image/"));
    if (imageItems.length === 0) return;
    e.preventDefault();
    imageItems.forEach((item) => {
      const file = item.getAsFile();
      if (!file) return;
      const named = new File([file], file.name || `pasted-image-${Date.now()}.png`, { type: file.type });
      processFile(named);
    });
  }

  // ── Submit ─────────────────────────────────────────

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mentionOpen && e.key === "Escape") {
      setMentionOpen(false);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function updateMentionState(val: string, caret: number) {
    const before = val.slice(0, caret);
    const at = before.lastIndexOf("@");
    if (at >= 0 && (at === 0 || /\s/.test(before[at - 1]))) {
      const frag = before.slice(at + 1);
      if (!frag.includes(" ") && !frag.includes("\n")) {
        setMentionOpen(true);
        setMentionFilter(frag.toLowerCase());
        return;
      }
    }
    setMentionOpen(false);
    setMentionFilter("");
  }

  function insertMention(slug: string) {
    const el = textareaRef.current;
    if (!el) return;
    const val = draft;
    const caret = el.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const after = val.slice(caret);
    const at = before.lastIndexOf("@");
    if (at < 0) return;
    const next = `${before.slice(0, at)}@${slug} ${after}`;
    setDraft(next);
    setMentionOpen(false);
    setMentionFilter("");
    requestAnimationFrame(() => {
      el.focus();
      const pos = at + slug.length + 2;
      el.setSelectionRange(pos, pos);
    });
  }

  const mentionMatches = mentionOpen
    ? topicSlugs.filter((s) => s.toLowerCase().includes(mentionFilter)).slice(0, 8)
    : [];

  function submit() {
    const text = draft.trim();
    const hasFiles = pendingFiles.some((f) => !f.loading);
    if ((!text && !hasFiles) || streaming) return;
    const files = pendingFiles
      .filter((f) => !f.loading)
      .map(({ name, text, thumb }) => ({ name, text, thumb }));
    setDraft("");
    try { localStorage.removeItem(draftKey(sessionId)); } catch { /* ignore */ }
    setPendingFiles([]);
    snapToBottom();
    onSend(text, [], files);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setDraft(val);
    updateMentionState(val, e.target.selectionStart ?? val.length);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  // ── Voice input (Web Speech API) ────────────────────
  function toggleVoice() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    if (!SpeechRecognitionImpl) return;
    const rec = new SpeechRecognitionImpl();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    const baseDraft = draft ? draft + " " : "";
    let finalText = "";
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      setDraft(baseDraft + finalText + interim);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => { setListening(false); recognitionRef.current = null; };
    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }

  // ── Message actions ────────────────────────────────

  async function handleDeleteMsg(msgId: number) {
    if (!sessionId) return;
    await onDeleteMessage(msgId);
  }

  const isLoading = pendingFiles.some((f) => f.loading);
  const canSend = (draft.trim().length > 0 || pendingFiles.some((f) => !f.loading)) && !streaming && !isLoading;

  return (
    <div
      className={`chat-area${dragOver ? " drag-over" : ""}${privateMode ? " chat-area--private" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="drop-overlay">
          <div className="drop-overlay-inner">Drop file to attach</div>
        </div>
      )}

      {/* Desktop topbar — hidden on mobile (mobile-header handles it) */}
      <div className="chat-topbar">
        <button
          className={`private-toggle private-toggle--topbar${privateMode ? " private-toggle--active" : ""}`}
          onClick={() => onPrivateModeChange(!privateMode)}
          type="button"
          disabled={streaming || privateLocked}
          title={privateLocked ? "Private mode is locked for this conversation" : "Private mode · conversation won't be saved to memory"}
        >
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13">
            <path d="M8 1.5C5.5 1.5 3.5 3.7 3.5 6.5c0 1 .3 2 .8 2.8L3 11c-.3.5 0 1 .6 1H5l.5 1.5c.2.5.7.5 1 0L7 12h2l.5 1.5c.2.5.7.5 1 0L11 11h1.4c.6 0 .9-.5.6-1l-1.3-1.7c.5-.8.8-1.8.8-2.8 0-2.8-2-5-4.5-5z" fill="currentColor"/>
            <circle cx="6" cy="7" r="1" fill="white" opacity="0.6"/>
            <circle cx="10" cy="7" r="1" fill="white" opacity="0.6"/>
          </svg>
          Private
        </button>
      </div>

      {/* Mobile header — hidden on desktop */}
      <div className="mobile-header">
        <button className="hamburger-btn" onClick={onMenuOpen} aria-label="Open menu">
          <span /><span /><span />
        </button>
        <span className="mobile-title">tinybeaver</span>
        <button
          className={`private-toggle private-toggle--topbar${privateMode ? " private-toggle--active" : ""}`}
          onClick={() => onPrivateModeChange(!privateMode)}
          type="button"
          disabled={streaming || privateLocked}
          title={privateLocked ? "Private mode is locked for this conversation" : "Private mode · conversation won't be saved to memory"}
        >
          <svg viewBox="0 0 16 16" fill="none" width="13" height="13">
            <path d="M8 1.5C5.5 1.5 3.5 3.7 3.5 6.5c0 1 .3 2 .8 2.8L3 11c-.3.5 0 1 .6 1H5l.5 1.5c.2.5.7.5 1 0L7 12h2l.5 1.5c.2.5.7.5 1 0L11 11h1.4c.6 0 .9-.5.6-1l-1.3-1.7c.5-.8.8-1.8.8-2.8 0-2.8-2-5-4.5-5z" fill="currentColor"/>
            <circle cx="6" cy="7" r="1" fill="white" opacity="0.6"/>
            <circle cx="10" cy="7" r="1" fill="white" opacity="0.6"/>
          </svg>
          Private
        </button>
      </div>

      {privateMode && (
        <div className="private-banner">
          <svg viewBox="0 0 20 20" fill="none" width="14" height="14" aria-hidden="true">
            <path d="M10 2C7 2 4.5 4.5 4.5 8v1H3a1 1 0 00-1 1v7a1 1 0 001 1h14a1 1 0 001-1V10a1 1 0 00-1-1h-1.5V8C15.5 4.5 13 2 10 2zm0 2c2 0 3.5 1.5 3.5 4v1h-7V8C6.5 5.5 8 4 10 4z" fill="currentColor" opacity="0.7"/>
            <circle cx="10" cy="13.5" r="1.5" fill="currentColor" opacity="0.5"/>
          </svg>
          Private · not saved to memory — refreshing the page will lose this chat
        </div>
      )}

      <div className="messages" ref={scrollRef} onScroll={handleScroll}>
        {loadingSession ? (
          <div className="session-skeleton" aria-label="Loading conversation">
            <div className="skeleton-row skeleton-row--user"><div className="skeleton-line" style={{ width: "38%" }} /></div>
            <div className="skeleton-row"><div className="skeleton-line" style={{ width: "82%" }} /><div className="skeleton-line" style={{ width: "70%" }} /><div className="skeleton-line" style={{ width: "48%" }} /></div>
            <div className="skeleton-row skeleton-row--user"><div className="skeleton-line" style={{ width: "30%" }} /></div>
            <div className="skeleton-row"><div className="skeleton-line" style={{ width: "76%" }} /><div className="skeleton-line" style={{ width: "60%" }} /></div>
          </div>
        ) : messages.length === 0 ? (
            <div className="empty-state">
              <img src="/favicon.png" alt="tinybeaver" className={`empty-state-logo${privateMode ? " empty-state-logo--private" : ""}`} />
            </div>
        ) : (
          messages.map((m, i) => {
            // Regenerate re-runs the user turn preceding this assistant message.
            let onRegenerate: (() => void) | undefined;
            if (m.role === "assistant" && m.id && !streaming) {
              for (let j = i - 1; j >= 0; j--) {
                const prev = messages[j];
                if (prev.role === "user" && prev.id) {
                  const uid = prev.id;
                  const utext = prev.content;
                  onRegenerate = () => onResend(uid, utext);
                  break;
                }
              }
            }
            return (
              <MessageBubble
                key={m.id ?? i}
                message={m}
                sessionId={sessionId}
                onResend={onResend}
                onRegenerate={onRegenerate}
                onRetry={m.isError ? onRetry : undefined}
                onContinue={m.stopped && m.id && !streaming ? () => onContinue(m.id!) : undefined}
                onDelete={handleDeleteMsg}
              />
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      {showScrollBtn && (
        <button className="scroll-bottom-btn" onClick={snapToBottom} title="Jump to latest" aria-label="Jump to latest">
          <svg viewBox="0 0 16 16" fill="none" width="16" height="16">
            <path d="M8 2.5v9m0 0L4 7.5m4 4l4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      )}

      <div className="input-bar">
        {/* File chips */}
        {pendingFiles.length > 0 && (
          <div className="file-chips">
            {pendingFiles.map((f, i) => (
              <div key={f.key ?? i} className={`file-chip${f.loading ? " file-chip--loading" : ""}${f.thumb ? " file-chip--pdf" : ""}`}>
                {f.thumb
                  ? <img src={f.thumb} alt="Preview" className="file-chip-thumb" title="Click to preview" onClick={() => setPdfPreview(f.thumb!)} />
                  : <span className="file-chip-icon">{f.loading ? "⏳" : fileIcon(f.name)}</span>}
                <div className="file-chip-info">
                  <span className="file-chip-name">{f.name}</span>
                  {!f.loading && (
                    <span className="file-chip-size">
                      {f.sizeKb > 0 ? `${f.sizeKb} KB` : ""}
                      {f.costUsd && f.costUsd > 0.00001 ? ` · ${f.costUsd < 0.01 ? `${(f.costUsd * 100).toFixed(2)}¢` : `$${f.costUsd.toFixed(4)}`}` : ""}
                    </span>
                  )}
                  {f.loading && <span className="file-chip-size">Reading with Flash…</span>}
                </div>
                {!f.loading && (
                  <button className="file-chip-remove" onClick={() => removeFile(i)} title="Remove"><Icon name="close" size={11} /></button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="input-compose">
          {mentionOpen && mentionMatches.length > 0 && (
            <div className="mention-dropdown" role="listbox">
              {mentionMatches.map((slug) => (
                <button
                  key={slug}
                  type="button"
                  className="mention-option"
                  onMouseDown={(e) => { e.preventDefault(); insertMention(slug); }}
                >
                  @{slug}
                </button>
              ))}
            </div>
          )}
        <div className="input-wrap">
          <button
            className="attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || isLoading}
            title="Attach file (PDF, CSV, TXT, image)"
          >
            <Icon name="attach" size={17} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf,.csv,.txt,.md,.json,.xlsx,.xlsm,.tsv"
            multiple
            style={{ display: "none" }}
            onChange={handleFileInput}
          />
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="Message… (@topic to load memory)"
            value={draft}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={streaming}
            autoComplete="off"
            autoCorrect="off"
            onClick={(e) => updateMentionState(draft, (e.target as HTMLTextAreaElement).selectionStart ?? draft.length)}
            onTouchStart={() => {
              const el = textareaRef.current;
              if (!el) return;
              // Remove readOnly and focus synchronously within the user gesture
              // so iOS opens keyboard exactly once with the correct caret position
              el.readOnly = false;
              el.focus();
            }}
            onBlur={() => {
              // Restore readOnly when keyboard closes so next tap is also clean
              const el = textareaRef.current;
              if (el && isMobile()) {
                setTimeout(() => {
                  if (document.activeElement !== el) el.readOnly = true;
                }, 100);
              }
            }}
          />
          {SpeechRecognitionImpl && !streaming && (
            <button
              className={`voice-btn${listening ? " voice-btn--active" : ""}`}
              onClick={toggleVoice}
              type="button"
              title={listening ? "Stop dictation" : "Dictate"}
              aria-label={listening ? "Stop dictation" : "Dictate"}
            >
              <svg viewBox="0 0 16 16" fill="none" width="16" height="16">
                <rect x="6" y="1.5" width="4" height="8" rx="2" fill="currentColor"/>
                <path d="M3.5 7a4.5 4.5 0 009 0M8 11.5v3M5.5 14.5h5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
              </svg>
            </button>
          )}
          {streaming ? (
            <button className="send-btn" onClick={onCancel} title="Stop"><Icon name="stop" size={14} /></button>
          ) : (
            <button className="send-btn" onClick={submit} disabled={!canSend} title="Send (Enter)"><Icon name="send" size={17} /></button>
          )}
        </div>
        </div>
        <div className="model-selector-row">
          <div className="model-selector-left">
            <ModelDropdown model={model} onModelChange={onModelChange} disabled={streaming || multiAgent} />
            <button
              className={`moa-toggle${multiAgent ? " moa-toggle--active" : ""}`}
              onClick={() => onMultiAgentChange(!multiAgent)}
              type="button"
              disabled={streaming}
              title={moaPipelineLabel()}
            >
              <svg viewBox="0 0 14 14" fill="none" width="12" height="12">
                <circle cx="3" cy="7" r="2" fill="currentColor" opacity="0.7"/>
                <circle cx="7" cy="3" r="2" fill="currentColor" opacity="0.7"/>
                <circle cx="11" cy="7" r="2" fill="currentColor" opacity="0.7"/>
                <path d="M5 7h2M7 5v2M7 7l2 0" stroke="currentColor" strokeWidth="1" opacity="0.5"/>
              </svg>
              Multi
            </button>
            {multiAgent && (
              <span className="moa-pipeline-hint" title={moaPipelineLabel()}>
                {moaPipelineLabel()}
              </span>
            )}
          </div>
          <span className="input-hint-inline desktop-only">Enter to send · Shift+Enter for newline</span>
        </div>
      </div>

      {pdfPreview && (
        <div className="lightbox-backdrop" onClick={() => setPdfPreview(null)}>
          <img src={pdfPreview} alt="PDF preview" className="lightbox-img" />
          <button className="lightbox-close" onClick={() => setPdfPreview(null)} aria-label="Close"><Icon name="close" /></button>
        </div>
      )}
    </div>
  );
});

export default ChatView;
