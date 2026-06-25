import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import MessageBubble from "./MessageBubble";
import type { Message } from "../hooks/useChat";
import type { AttachedFile } from "../lib/api";
import { deleteMessage, extractFile } from "../lib/api";

interface PendingFile extends AttachedFile {
  sizeKb: number;
  costUsd?: number;
  loading?: boolean;
}

interface Props {
  messages: Message[];
  streaming: boolean;
  sessionId: string | null;
  onSend: (text: string, images: string[], files: AttachedFile[]) => void;
  onCancel: () => void;
  onResend: (msgId: number, newContent: string) => void;
}

export interface ChatViewHandle {
  focusInput: () => void;
  setDraft: (text: string) => void;
}

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "📄";
  if (ext === "csv") return "📊";
  if (["md", "txt"].includes(ext)) return "📝";
  if (["json"].includes(ext)) return "{ }";
  return "📎";
}

const ChatView = forwardRef<ChatViewHandle, Props>(function ChatView({ messages, streaming, sessionId, onSend, onCancel, onResend }, ref) {
  const [draft, setDraft] = useState("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pinnedRef = useRef(true);

  useImperativeHandle(ref, () => ({
    focusInput: () => textareaRef.current?.focus(),
    setDraft: (text: string) => {
      setDraft(text);
      setTimeout(() => textareaRef.current?.focus(), 50);
    },
  }));

  // Auto-focus textarea whenever the active session changes or new chat opens
  useEffect(() => {
    if (!streaming) {
      setTimeout(() => textareaRef.current?.focus(), 80);
    }
  }, [sessionId]);

  useEffect(() => {
    if (messages.length === 0) {
      pinnedRef.current = true;
      setTimeout(() => textareaRef.current?.focus(), 80);
    }
  }, [messages.length === 0]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  useEffect(() => {
    if (pinnedRef.current) {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  function snapToBottom() {
    pinnedRef.current = true;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  // ── File handling ──────────────────────────────────

  async function processFile(file: File) {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (["jpg", "jpeg", "png", "gif", "webp"].includes(ext)) {
      const reader = new FileReader();
      reader.onload = (e) => {
        const url = e.target?.result as string;
        if (url) setPendingImages((p) => [...p, url]);
      };
      reader.readAsDataURL(file);
      return;
    }

    // Show chip in loading state immediately
    const placeholder: PendingFile = { name: file.name, text: "", sizeKb: 0, loading: true };
    setPendingFiles((p) => [...p, placeholder]);

    try {
      const result = await extractFile(file);
      setPendingFiles((p) =>
        p.map((f) =>
          f === placeholder
            ? { name: result.filename, text: result.text, sizeKb: result.size_kb, costUsd: result.cost_usd, loading: false }
            : f
        )
      );
    } catch (e: any) {
      // Remove placeholder and show error
      setPendingFiles((p) => p.filter((f) => f !== placeholder));
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
      const reader = new FileReader();
      reader.onload = (ev) => {
        const url = ev.target?.result as string;
        if (url) setPendingImages((prev) => [...prev, url]);
      };
      reader.readAsDataURL(file);
    });
  }

  // ── Submit ─────────────────────────────────────────

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = draft.trim();
    const hasFiles = pendingFiles.some((f) => !f.loading);
    if ((!text && pendingImages.length === 0 && !hasFiles) || streaming) return;
    const imgs = pendingImages;
    const files = pendingFiles.filter((f) => !f.loading).map(({ name, text }) => ({ name, text }));
    setDraft("");
    setPendingImages([]);
    setPendingFiles([]);
    snapToBottom();
    onSend(text, imgs, files);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setDraft(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  function removeImage(idx: number) {
    setPendingImages((prev) => prev.filter((_, i) => i !== idx));
  }

  // ── Message actions ────────────────────────────────

  async function handleDeleteMsg(msgId: number) {
    if (!sessionId) return;
    await deleteMessage(sessionId, msgId);
  }

  const isLoading = pendingFiles.some((f) => f.loading);
  const canSend = (draft.trim().length > 0 || pendingImages.length > 0 || pendingFiles.some((f) => !f.loading)) && !streaming && !isLoading;

  return (
    <div
      className={`chat-area${dragOver ? " drag-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {dragOver && (
        <div className="drop-overlay">
          <div className="drop-overlay-inner">Drop file to attach</div>
        </div>
      )}

      <div className="messages" ref={scrollRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="empty-state">
            <h2>What's on your mind?</h2>
            <p>Ask anything — your memory context loads automatically.</p>
          </div>
        ) : (
          messages.map((m, i) => (
            <MessageBubble
              key={m.id ?? i}
              message={m}
              sessionId={sessionId}
              onResend={onResend}
              onDelete={handleDeleteMsg}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-bar">
        {/* Image previews */}
        {pendingImages.length > 0 && (
          <div className="image-previews">
            {pendingImages.map((src, i) => (
              <div key={i} className="image-preview-wrap">
                <img src={src} alt={`pasted ${i + 1}`} className="image-preview" />
                <button className="image-remove" onClick={() => removeImage(i)} title="Remove">✕</button>
              </div>
            ))}
          </div>
        )}

        {/* File chips */}
        {pendingFiles.length > 0 && (
          <div className="file-chips">
            {pendingFiles.map((f, i) => (
              <div key={i} className={`file-chip${f.loading ? " file-chip--loading" : ""}`}>
                <span className="file-chip-icon">{f.loading ? "⏳" : fileIcon(f.name)}</span>
                <div className="file-chip-info">
                  <span className="file-chip-name">{f.name}</span>
                  {!f.loading && (
                    <span className="file-chip-size">
                      {f.sizeKb > 0 ? `${f.sizeKb} KB` : ""}
                      {f.costUsd && f.costUsd > 0.00001 ? ` · ${f.costUsd < 0.01 ? `${(f.costUsd * 100).toFixed(2)}¢` : `$${f.costUsd.toFixed(4)}`}` : ""}
                    </span>
                  )}
                  {f.loading && <span className="file-chip-size">Extracting…</span>}
                </div>
                {!f.loading && (
                  <button className="file-chip-remove" onClick={() => removeFile(i)} title="Remove">✕</button>
                )}
              </div>
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
            ⊕
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.csv,.txt,.md,.json,.png,.jpg,.jpeg,.gif,.webp"
            multiple
            style={{ display: "none" }}
            onChange={handleFileInput}
          />
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="Message… (Ctrl+V to paste image)"
            value={draft}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={streaming}
          />
          {streaming ? (
            <button className="send-btn" onClick={onCancel} title="Stop">■</button>
          ) : (
            <button className="send-btn" onClick={submit} disabled={!canSend} title="Send (Enter)">↑</button>
          )}
        </div>
        <p className="input-hint">Enter to send · Shift+Enter for newline · Drop or ⊕ to attach file</p>
      </div>
    </div>
  );
});

export default ChatView;
