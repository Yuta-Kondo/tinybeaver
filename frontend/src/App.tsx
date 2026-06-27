import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView, { type ChatViewHandle } from "./components/ChatView";
import { useChat } from "./hooks/useChat";
import { deleteSession, fetchSessions, type SessionInfo } from "./lib/api";

export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const chatViewRef = useRef<ChatViewHandle>(null);
  const { messages, streaming, sendMessage, resendFromMessage, cancel, clear, loadSession } =
    useChat(activeId);

  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {});
  }, []);

  const handleNewSession = useCallback((id: string) => {
    setActiveId(id);
    fetchSessions().then(setSessions).catch(() => {});
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      // Cmd/Ctrl+Shift+O — new chat (same as Claude.ai)
      if (mod && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        handleNew();
        setSidebarOpen(false);
        return;
      }
      // Cmd/Ctrl+K — focus search
      if (mod && e.key === "k") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("focus-search"));
        return;
      }
      // Any printable key when nothing is focused → focus chat input
      const tag = (e.target as HTMLElement)?.tagName;
      if (!mod && !e.altKey && tag !== "INPUT" && tag !== "TEXTAREA" && e.key.length === 1) {
        chatViewRef.current?.focusInput();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function handleNew() {
    setActiveId(null);
    clear();
  }

  function handleSelect(id: string) {
    if (id === activeId) return;
    setActiveId(id);
    loadSession(id);
  }

  async function handleDelete(id: string) {
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.session_id !== id));
    if (id === activeId) {
      setActiveId(null);
      clear();
    }
  }

  function handleSend(text: string, images: string[], files: import("./lib/api").AttachedFile[]) {
    sendMessage(text, handleNewSession, images, files);
  }

  function handleResend(msgId: number, newContent: string) {
    resendFromMessage(msgId, newContent, handleNewSession);
  }

  // Pre-fill the chat textarea with text (e.g. email content sent from GmailPanel)
  function handleSendToChat(text: string) {
    chatViewRef.current?.setDraft(text);
    chatViewRef.current?.focusInput();
  }

  return (
    <div className="app">
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={(id) => { handleSelect(id); setSidebarOpen(false); }}
        onNew={() => { handleNew(); setSidebarOpen(false); }}
        onDelete={handleDelete}
        onSendToChat={(t) => { handleSendToChat(t); setSidebarOpen(false); }}
        isOpen={sidebarOpen}
      />
      <ChatView
        ref={chatViewRef}
        messages={messages}
        streaming={streaming}
        sessionId={activeId}
        onSend={handleSend}
        onCancel={cancel}
        onResend={handleResend}
        onMenuOpen={() => setSidebarOpen(true)}
      />
    </div>
  );
}
