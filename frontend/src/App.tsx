import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView, { type ChatViewHandle } from "./components/ChatView";
import CommandPalette, { type Command } from "./components/CommandPalette";
import { useChat } from "./hooks/useChat";
import { deleteSession, fetchSessions, type SessionInfo } from "./lib/api";

const PALETTE_MODELS = [
  { id: "claude-haiku-4-5-20251001", name: "Haiku 4.5" },
  { id: "claude-sonnet-4-6", name: "Sonnet 4.6" },
  { id: "claude-sonnet-5", name: "Sonnet 5" },
  { id: "claude-opus-4-8", name: "Opus 4.8" },
  { id: "gemini-3.5-flash", name: "Flash 3.5" },
  { id: "glm-5.2", name: "GLM 5.2" },
];

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function registerPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;

    const existing = await reg.pushManager.getSubscription();
    if (existing) return; // already subscribed

    const perm = await Notification.requestPermission();
    if (perm !== "granted") return;

    const resp = await fetch("/push/vapid-public-key");
    const { public_key } = await resp.json();
    if (!public_key) return;

    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    });

    await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub.toJSON()),
    });
  } catch (e) {
    console.warn("Push registration failed:", e);
  }
}

export default function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const VALID_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-8", "gemini-3.5-flash", "glm-5.2"];
  const [model, setModel] = useState(() => {
    const stored = localStorage.getItem("selectedModel") ?? "";
    return VALID_MODELS.includes(stored) ? stored : "claude-sonnet-5";
  });
  const [multiAgent, setMultiAgent] = useState(() => localStorage.getItem("multiAgent") === "1");
  const [privateMode, setPrivateMode] = useState(false);
  const [privateLocked, setPrivateLocked] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const chatViewRef = useRef<ChatViewHandle>(null);
  const sidebarOpenRef = useRef(false);
  const { messages, streaming, loadingSession, sendMessage, resendFromMessage, retryLast, continueMessage, cancel, clear, loadSession } =
    useChat(activeId);

  function handleModelChange(m: string) {
    setModel(m);
    localStorage.setItem("selectedModel", m);
  }

  function handleMultiAgentChange(v: boolean) {
    setMultiAgent(v);
    localStorage.setItem("multiAgent", v ? "1" : "0");
  }

  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {});
    registerPush();
  }, []);

  // Keep ref in sync so swipe handler always sees current state
  useEffect(() => { sidebarOpenRef.current = sidebarOpen; }, [sidebarOpen]);

  // Swipe-from-left-edge to open sidebar (mobile)
  useEffect(() => {
    const EDGE = 24;
    let startX = 0, startY = 0, active = false;
    let sidebarEl: HTMLElement | null = null;

    function onStart(e: TouchEvent) {
      if (e.touches[0].clientX > EDGE || sidebarOpenRef.current) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      active = true;
      sidebarEl = document.querySelector<HTMLElement>(".sidebar");
      if (sidebarEl) sidebarEl.style.transition = "none";
    }

    function onMove(e: TouchEvent) {
      if (!active || !sidebarEl) return;
      const dx = e.touches[0].clientX - startX;
      const dy = Math.abs(e.touches[0].clientY - startY);
      if (dy > Math.abs(dx)) { active = false; sidebarEl.style.transition = ""; return; }
      const w = sidebarEl.offsetWidth;
      const clamped = Math.max(0, Math.min(dx, w));
      sidebarEl.style.transform = `translateX(${clamped - w}px)`;
    }

    function onEnd(e: TouchEvent) {
      if (!active || !sidebarEl) return;
      const dx = e.changedTouches[0].clientX - startX;
      sidebarEl.style.transition = "";
      sidebarEl.style.transform = "";
      if (dx > 60) setSidebarOpen(true);
      active = false;
    }

    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: true });
    document.addEventListener("touchend", onEnd, { passive: true });
    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
    };
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
      // Cmd/Ctrl+K — command palette
      if (mod && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
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
    setPrivateMode(false);
    setPrivateLocked(false);
  }

  function handleSelect(id: string) {
    if (id === activeId) return;
    setActiveId(id);
    loadSession(id);
    setPrivateMode(false);
    setPrivateLocked(false);
  }

  async function handleDelete(id: string) {
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.session_id !== id));
    if (id === activeId) {
      setActiveId(null);
      clear();
    }
  }

  function handleRenamed(id: string, title: string) {
    setSessions((prev) => prev.map((s) => (s.session_id === id ? { ...s, title } : s)));
  }

  function openSidebarTab(tab: "chats" | "memory" | "tasks" | "email") {
    setSidebarOpen(true);
    window.dispatchEvent(new CustomEvent("open-sidebar-tab", { detail: tab }));
  }

  const paletteCommands: Command[] = [
    { id: "new-chat", label: "New chat", hint: "⌘⇧O", group: "Actions", run: () => { handleNew(); setSidebarOpen(false); } },
    { id: "search", label: "Search chats", hint: "", group: "Actions", run: () => openSidebarTab("chats") },
    {
      id: "toggle-private",
      label: privateMode ? "Turn off private mode" : "Turn on private mode",
      group: "Actions",
      run: () => { if (!privateLocked) { setPrivateMode((v) => !v); if (privateMode) setPrivateLocked(false); } },
    },
    {
      id: "toggle-moa",
      label: multiAgent ? "Disable multi-agent" : "Enable multi-agent",
      group: "Actions",
      run: () => handleMultiAgentChange(!multiAgent),
    },
    ...PALETTE_MODELS.map((m) => ({
      id: `model:${m.id}`,
      label: `Switch to ${m.name}`,
      hint: m.id === model ? "current" : "",
      group: "Model",
      run: () => handleModelChange(m.id),
    })),
    { id: "open-memory", label: "Open Memory", group: "Panels", run: () => openSidebarTab("memory") },
    { id: "open-tasks", label: "Open Tasks", group: "Panels", run: () => openSidebarTab("tasks") },
    { id: "open-email", label: "Open Email", group: "Panels", run: () => openSidebarTab("email") },
  ];

  function handleSend(text: string, images: string[], files: import("./lib/api").AttachedFile[]) {
    if (privateMode) setPrivateLocked(true);
    sendMessage(text, handleNewSession, images, files, model, multiAgent, privateMode);
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
        onRenamed={handleRenamed}
        onSendToChat={(t) => { handleSendToChat(t); setSidebarOpen(false); }}
        isOpen={sidebarOpen}
      />
      <ChatView
        ref={chatViewRef}
        messages={messages}
        streaming={streaming}
        loadingSession={loadingSession}
        sessionId={activeId}
        onSend={handleSend}
        onCancel={cancel}
        onResend={handleResend}
        onRetry={retryLast}
        onContinue={continueMessage}
        onMenuOpen={() => setSidebarOpen(true)}
        model={model}
        onModelChange={handleModelChange}
        multiAgent={multiAgent}
        onMultiAgentChange={handleMultiAgentChange}
        privateMode={privateMode}
        privateLocked={privateLocked}
        onPrivateModeChange={(v) => { setPrivateMode(v); if (!v) setPrivateLocked(false); }}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={paletteCommands}
        sessions={sessions}
        onSelectSession={(id) => { handleSelect(id); setSidebarOpen(false); }}
      />
    </div>
  );
}
