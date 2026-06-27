import { useEffect, useRef, useState } from "react";
import type { SessionInfo, SessionSearchResult } from "../lib/api";
import { searchSessions } from "../lib/api";
import TopicsPanel from "./TopicsPanel";
import TasksPanel from "./TasksPanel";
import GmailPanel from "./GmailPanel";

interface Props {
  sessions: SessionInfo[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onSendToChat: (text: string) => void;
  isOpen?: boolean;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete, onSendToChat, isOpen }: Props) {
  const [tab, setTab] = useState<"chats" | "memory" | "tasks" | "email">("chats");
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionSearchResult[]>([]);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/cdn-cgi/access/get-identity")
      .then((r) => r.json())
      .then((d) => { if (d?.email) setUserEmail(d.email); })
      .catch(() => {});
  }, []);

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
    <aside className={`sidebar${isOpen ? " sidebar--open" : ""}`}>
      <div className="sidebar-header">
        <div className="sidebar-title">tinybeaver</div>
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
              <span className="shortcut-item"><kbd className="kbd">⌘⇧O</kbd> <span>new chat</span></span>
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

      {userEmail && (
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <span className="sidebar-user-email">{userEmail}</span>
            <a className="sidebar-signout" href="/cdn-cgi/access/logout">Sign out</a>
          </div>
        </div>
      )}
    </aside>
  );
}
