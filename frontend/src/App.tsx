import { useCallback, useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import { useChat } from "./hooks/useChat";
import { deleteSession, fetchSessions, type SessionInfo } from "./lib/api";

export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  const { messages, streaming, sendMessage, resendFromMessage, cancel, clear, loadSession } =
    useChat(activeId);

  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {});
  }, []);

  const handleNewSession = useCallback((id: string) => {
    setActiveId(id);
    fetchSessions().then(setSessions).catch(() => {});
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

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <ChatView
        messages={messages}
        streaming={streaming}
        sessionId={activeId}
        onSend={handleSend}
        onCancel={cancel}
        onResend={handleResend}
      />
    </div>
  );
}
