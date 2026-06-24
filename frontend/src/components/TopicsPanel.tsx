import { useCallback, useEffect, useRef, useState } from "react";
import {
  type SearchResult,
  type TopicDetail,
  type TopicSummary,
  createTopic,
  fetchTopic,
  fetchTopics,
  reflect,
  saveTopic,
  searchTopics,
  semanticSearchTopics,
} from "../lib/api";

export default function TopicsPanel() {
  const [topics, setTopics] = useState<TopicSummary[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [selected, setSelected] = useState<TopicDetail | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [reflecting, setReflecting] = useState(false);
  const [reflectMsg, setReflectMsg] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [creatingNew, setCreatingNew] = useState(false);
  const [error, setError] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadTopics = useCallback(async () => {
    try {
      setTopics(await fetchTopics());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadTopics();
  }, [loadTopics]);

  // Debounced search: semantic first, fall back to FTS
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!query.trim()) { setSearchResults(null); return; }
    searchTimer.current = setTimeout(async () => {
      try {
        // Try semantic search first
        const sem = await semanticSearchTopics(query.trim());
        if (sem.length > 0) {
          setSearchResults(sem.map((r) => ({ slug: r.slug, snippet: `score: ${r.score}` })));
        } else {
          setSearchResults(await searchTopics(query.trim()));
        }
      } catch {
        setSearchResults(await searchTopics(query.trim()).catch(() => []));
      }
    }, 300);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [query]);

  async function openTopic(slug: string) {
    try {
      const detail = await fetchTopic(slug);
      setSelected(detail);
      setEditContent(detail.content);
      setError("");
    } catch {
      setError("Failed to load topic.");
    }
  }

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await saveTopic(selected.slug, editContent, selected.description);
      setSelected({ ...selected, content: editContent, updated_at: new Date().toISOString() });
    } catch {
      setError("Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReflect() {
    setReflecting(true);
    setReflectMsg("");
    setError("");
    try {
      const updated = await reflect();
      setReflectMsg(
        updated.length
          ? `Consolidated: ${updated.join(", ")}`
          : "All topics look clean — nothing changed."
      );
      // Refresh open topic if it was updated
      if (selected && updated.includes(selected.slug)) {
        openTopic(selected.slug);
      }
    } catch {
      setError("Reflect failed.");
    } finally {
      setReflecting(false);
    }
  }

  async function handleCreate() {
    const slug = newSlug.trim().toLowerCase().replace(/\s+/g, "-");
    if (!slug) return;
    setError("");
    try {
      await createTopic(slug);
      setNewSlug("");
      setCreatingNew(false);
      await loadTopics();
      openTopic(slug);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Create failed.");
    }
  }

  const displayList = searchResults
    ? searchResults.map((r) => ({ slug: r.slug, description: r.snippet }))
    : topics;

  return (
    <div className="topics-panel">
      {/* Search + actions */}
      <div className="topics-search-bar">
        <input
          type="text"
          placeholder="Search memory…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="topics-search-input"
        />
      </div>

      {/* Topic list */}
      <div className="topics-list">
        {displayList.length === 0 && query && (
          <p className="topics-empty">No results for "{query}"</p>
        )}
        {displayList.map((t) => (
          <button
            key={t.slug}
            className={`topic-row ${selected?.slug === t.slug ? "active" : ""}`}
            onClick={() => openTopic(t.slug)}
          >
            <span className="topic-slug">{t.slug}</span>
            {t.description && (
              <span
                className="topic-desc"
                dangerouslySetInnerHTML={{ __html: t.description.replace(/\*\*(.*?)\*\*/g, "<mark>$1</mark>") }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Footer: new topic + reflect */}
      <div className="topics-footer">
        {creatingNew ? (
          <div className="new-topic-row">
            <input
              type="text"
              placeholder="slug (e.g. gym)"
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              className="new-slug-input"
              autoFocus
            />
            <button className="icon-btn" onClick={handleCreate} title="Create">✓</button>
            <button className="icon-btn" onClick={() => { setCreatingNew(false); setNewSlug(""); }} title="Cancel">✕</button>
          </div>
        ) : (
          <button className="topics-footer-btn" onClick={() => setCreatingNew(true)}>
            + New topic
          </button>
        )}
        <button
          className="topics-footer-btn reflect-btn"
          onClick={handleReflect}
          disabled={reflecting}
          title="Ask Haiku to consolidate and clean all topics"
        >
          {reflecting ? "Reflecting…" : "⟳ Reflect"}
        </button>
      </div>

      {reflectMsg && <p className="reflect-msg">{reflectMsg}</p>}
      {error && <p className="topics-error">{error}</p>}

      {/* Editor drawer */}
      {selected && (
        <div className="topic-editor">
          <div className="topic-editor-header">
            <div>
              <strong className="topic-editor-slug">{selected.slug}</strong>
              {selected.description && (
                <span className="topic-editor-desc"> — {selected.description}</span>
              )}
            </div>
            <div className="topic-editor-meta">
              {selected.updated_at
                ? new Date(selected.updated_at).toLocaleString()
                : ""}
            </div>
            <button className="icon-btn" onClick={() => setSelected(null)} title="Close">✕</button>
          </div>
          <textarea
            className="topic-editor-textarea"
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            spellCheck={false}
          />
          <div className="topic-editor-actions">
            <button
              className="save-topic-btn"
              onClick={handleSave}
              disabled={saving || editContent === selected.content}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button className="cancel-topic-btn" onClick={() => setEditContent(selected.content)}>
              Reset
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
