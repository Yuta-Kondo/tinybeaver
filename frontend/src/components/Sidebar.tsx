import { useEffect, useRef, useState } from "react";
import type { SessionInfo, SessionSearchResult } from "../lib/api";
import { searchSessions } from "../lib/api";
import TopicsPanel from "./TopicsPanel";
import TasksPanel from "./TasksPanel";

interface Props {
  sessions: SessionInfo[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function Sidebar({ sessions, activeId, onSelect, onNew, onDelete }: Props) {
  const [tab, setTab] = useState<"chats" | "memory" | "tasks">("chats");
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionSearchResult[]>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
        <h1>Personal Agent</h1>
        <div className="sidebar-tabs">
          <button className={`sidebar-tab ${tab === "chats" ? "active" : ""}`} onClick={() => setTab("chats")}>
            Chats
          </button>
          <button className={`sidebar-tab ${tab === "memory" ? "active" : ""}`} onClick={() => setTab("memory")}>
            Memory
          </button>
          <button className={`sidebar-tab ${tab === "tasks" ? "active" : ""}`} onClick={() => setTab("tasks")}>
            Tasks
          </button>
        </div>
        {tab === "chats" && (
          <button className="new-chat-btn" onClick={onNew}>+ New chat</button>
        )}
      </div>

      {tab === "chats" ? (
        <>
          <div className="session-search-bar">
            <input
              className="session-search-input"
              placeholder="Search conversations…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
          </div>
          <div className="session-list">
            {displayList.length === 0 && searchQ ? (
              <p className="sessions-empty">No results for "{searchQ}"</p>
            ) : (
              displayList.map((s) => (
                <div
                  key={s.session_id}
                  className={`session-item ${s.session_id === activeId ? "active" : ""}`}
                  onClick={() => onSelect(s.session_id)}
                >
                  <div className="session-item-body">
                    <span className="session-title">{s.title}</span>
                    {s.snippet && (
                      <span
                        className="session-snippet"
                        dangerouslySetInnerHTML={{ __html: s.snippet.replace(/\*\*(.*?)\*\*/g, "<mark>$1</mark>") }}
                      />
                    )}
                  </div>
                  <button
                    className="session-delete"
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
      ) : (
        <TasksPanel />
      )}
    </aside>
  );
}
