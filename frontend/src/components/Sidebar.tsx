import { useEffect, useRef, useState } from "react";
import type { SessionInfo, SessionSearchResult } from "../lib/api";
import { searchSessions } from "../lib/api";
import TopicsPanel from "./TopicsPanel";
import TasksPanel from "./TasksPanel";
import GmailPanel from "./GmailPanel";
import type { Theme } from "../hooks/useTheme";

const THEMES: { id: Theme; label: string; color: string; border?: string }[] = [
  { id: "emerald", label: "Emerald",  color: "#3ecfa0" },
  { id: "violet",  label: "Violet",   color: "#9b72f0" },
  { id: "ocean",   label: "Ocean",    color: "#4fa8e8" },
  { id: "rose",    label: "Rose",     color: "#e07090" },
  { id: "slate",   label: "Slate",    color: "#8fa8be" },
  { id: "light",   label: "Light",    color: "#f3f7f5", border: "rgba(0,0,0,0.18)" },
];

interface Props {
  sessions: SessionInfo[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  theme: Theme;
  onThemeChange: (t: Theme) => void;
  onSendToChat: (text: string) => void;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete, theme, onThemeChange, onSendToChat }: Props) {
  const [tab, setTab] = useState<"chats" | "memory" | "tasks" | "email">("chats");
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionSearchResult[]>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onFocusSearch() {
      setTab("chats");
      setTimeout(() => searchInputRef.current?.focus(), 50);
    }
    window.addEventListener("focus-search", onFocusSearch);
    return () => window.removeEventListener("focus-search", onFocusSearch);
  }, []);

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!searchQ.trim()) { setSearchResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      const results = await searchSessions(searchQ).catch(() => []);
      setSearchResults(results);
    }, 300);
  }, [searchQ]);

  const displayList = searchQ.trim()
    ? searchResults.map((r) => ({ session_id: r.session_id, title: r.title, snippet: r.snippet }))
    : sessions.map((s) => ({ session_id: s.session_id, title: s.title, snippet: "" }));

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title">Personal Agent</div>
        <div className="sidebar-tabs">
          <button className={`tab-btn ${tab === "chats" ? "active" : ""}`} onClick={() => setTab("chats")}>Chats</button>
          <button className={`tab-btn ${tab === "memory" ? "active" : ""}`} onClick={() => setTab("memory")}>Memory</button>
          <button className={`tab-btn ${tab === "tasks" ? "active" : ""}`} onClick={() => setTab("tasks")}>Tasks</button>
          <button className={`tab-btn ${tab === "email" ? "active" : ""}`} onClick={() => setTab("email")}>Email</button>
        </div>
        {tab === "chats" && (
          <>
            <button className="new-chat-btn" onClick={onNew}>+ New chat</button>
            <div className="shortcut-bar">
              <span className="shortcut-item"><kbd className="kbd">⌘K</kbd> <span>search</span></span>
            </div>
          </>
        )}
      </div>

      {tab === "chats" ? (
        <>
          <div className="session-search">
            <input
              ref={searchInputRef}
              className="session-search-input"
              placeholder="Search…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
          </div>
          <div className="session-list">
            {displayList.length === 0 && searchQ ? (
              <p style={{ padding: "8px 12px", fontSize: 12, color: "var(--t3)" }}>No results for "{searchQ}"</p>
            ) : (
              displayList.map((s) => (
                <div
                  key={s.session_id}
                  className={`session-item ${s.session_id === activeId ? "active" : ""}`}
                  onClick={() => onSelect(s.session_id)}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="session-item-title">{s.title}</div>
                    {s.snippet && (
                      <div
                        className="session-search-snippet"
                        dangerouslySetInnerHTML={{ __html: s.snippet.replace(/\*\*(.*?)\*\*/g, "<mark>$1</mark>") }}
                      />
                    )}
                  </div>
                  <button
                    className="session-delete-btn"
                    onClick={(e) => { e.stopPropagation(); onDelete(s.session_id); }}
                    title="Delete"
                  >×</button>
                </div>
              ))
            )}
          </div>
        </>
      ) : tab === "memory" ? (
        <TopicsPanel />
      ) : tab === "tasks" ? (
        <TasksPanel />
      ) : (
        <GmailPanel onSendToChat={onSendToChat} />
      )}

      <div className="theme-picker">
        <span className="theme-picker-label">Theme</span>
        {THEMES.map((t) => (
          <button
            key={t.id}
            className={`theme-dot theme-dot--${t.id} ${theme === t.id ? "active" : ""}`}
            style={{ background: t.color, ...(t.border ? { outline: `1px solid ${t.border}`, outlineOffset: "-1px" } : {}) }}
            title={t.label}
            onClick={() => onThemeChange(t.id)}
          />
        ))}
      </div>
    </aside>
  );
}
