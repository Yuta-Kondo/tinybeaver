import { useCallback, useEffect, useRef, useState } from "react";
import {
  type MemoryFact,
  type SearchResult,
  type TopicDetail,
  type TopicSummary,
  addMemoryFact,
  deleteMemoryFact,
  fetchCoreProfile,
  fetchTopic,
  fetchTopics,
  reflect,
  reindexTopics,
  saveCoreProfile,
  searchTopics,
  semanticSearchTopics,
  updateMemoryFact,
} from "../lib/api";
import Icon from "./Icon";
import { WaitingIndicator } from "./WaitingIndicator";

export default function TopicsPanel() {
  const [topics, setTopics] = useState<TopicSummary[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [selected, setSelected] = useState<TopicDetail | null>(null);
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [core, setCore] = useState("");
  const [coreOpen, setCoreOpen] = useState(false);
  const [newFact, setNewFact] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [reflecting, setReflecting] = useState(false);
  const [reflectMsg, setReflectMsg] = useState("");
  const [error, setError] = useState("");
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");
  const [searching, setSearching] = useState(false);
  const [loadingSlug, setLoadingSlug] = useState<string | null>(null);
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
    fetchCoreProfile().then(setCore).catch(() => {});
  }, [loadTopics]);

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!query.trim()) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const sem = await semanticSearchTopics(query.trim());
        if (sem.length > 0) {
          setSearchResults(
            sem.map((r) => ({
              slug: r.slug,
              snippet: r.snippet || `score: ${r.score}`,
            }))
          );
        } else {
          setSearchResults(await searchTopics(query.trim()));
        }
      } catch {
        setSearchResults(await searchTopics(query.trim()).catch(() => []));
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [query]);

  async function openTopic(slug: string) {
    setLoadingSlug(slug);
    setCoreOpen(false);
    try {
      const detail = await fetchTopic(slug);
      setSelected(detail);
      setFacts(detail.facts ?? []);
      setError("");
      setEditingId(null);
      setNewFact("");
    } catch {
      setError("Failed to load category.");
    } finally {
      setLoadingSlug(null);
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
          ? `Consolidated graph (${updated.join(", ")})`
          : "Graph looks clean — nothing changed."
      );
      await loadTopics();
      if (selected) openTopic(selected.slug);
    } catch {
      setError("Reflect failed.");
    } finally {
      setReflecting(false);
    }
  }

  async function handleReindex() {
    setReindexing(true);
    setReindexMsg("");
    setError("");
    try {
      const count = await reindexTopics();
      setReindexMsg(`Re-embedded ${count} fact${count === 1 ? "" : "s"}.`);
    } catch {
      setError("Reindex failed.");
    } finally {
      setReindexing(false);
    }
  }

  async function handleAddFact() {
    if (!selected || !newFact.trim()) return;
    setSaving(true);
    try {
      await addMemoryFact(selected.slug, newFact.trim());
      setNewFact("");
      await openTopic(selected.slug);
      await loadTopics();
    } catch {
      setError("Could not add fact.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveFact(id: number) {
    if (!editText.trim()) return;
    setSaving(true);
    try {
      await updateMemoryFact(id, editText.trim());
      setEditingId(null);
      if (selected) await openTopic(selected.slug);
    } catch {
      setError("Could not update fact.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteFact(id: number) {
    if (!window.confirm("Remove this fact?")) return;
    try {
      await deleteMemoryFact(id);
      if (selected) await openTopic(selected.slug);
      await loadTopics();
    } catch {
      setError("Could not delete fact.");
    }
  }

  async function handleSaveCore() {
    setSaving(true);
    try {
      await saveCoreProfile(core);
      setReflectMsg("Core profile saved.");
    } catch {
      setError("Could not save core profile.");
    } finally {
      setSaving(false);
    }
  }

  const displayList = searchResults
    ? searchResults.map((r) => ({
        slug: r.slug,
        description: r.snippet,
        fact_count: undefined as number | undefined,
      }))
    : topics;

  return (
    <div className="topics-panel">
      <div className="topics-search-bar">
        <input
          type="text"
          placeholder="Search facts…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="topics-search-input"
        />
      </div>

      <div className="topics-list">
        <button
          className={`topic-row${coreOpen ? " active" : ""}`}
          onClick={() => {
            setCoreOpen(true);
            setSelected(null);
          }}
          type="button"
        >
          <span className="topic-slug">core profile</span>
          <span className="topic-desc">Always-on identity (capped)</span>
        </button>
        {searching && (
          <div className="topics-list-wait">
            <WaitingIndicator label="Searching memory…" size="sm" />
          </div>
        )}
        {!searching && displayList.length === 0 && query && (
          <p className="topics-empty">No results for "{query}"</p>
        )}
        {displayList.map((t) => (
          <button
            key={t.slug + (t.description || "")}
            className={`topic-row ${selected?.slug === t.slug && !coreOpen ? "active" : ""}${
              loadingSlug === t.slug ? " topic-row--loading" : ""
            }`}
            onClick={() => openTopic(t.slug)}
            type="button"
          >
            <span className="topic-slug">
              {t.slug}
              {typeof t.fact_count === "number" ? ` · ${t.fact_count}` : ""}
            </span>
            {t.description && (
              <span
                className="topic-desc"
                dangerouslySetInnerHTML={{
                  __html: t.description.replace(/\*\*(.*?)\*\*/g, "<mark>$1</mark>"),
                }}
              />
            )}
          </button>
        ))}
      </div>

      <div className="topics-footer">
        <button
          className="topics-footer-btn reflect-btn"
          onClick={handleReindex}
          disabled={reindexing}
          title="Re-embed all active facts"
          type="button"
        >
          {reindexing ? <WaitingIndicator label="Reindexing…" size="sm" /> : "↻ Reindex"}
        </button>
        <button
          className="topics-footer-btn reflect-btn"
          onClick={handleReflect}
          disabled={reflecting}
          title="Consolidate duplicates in the knowledge graph"
          type="button"
        >
          {reflecting ? <WaitingIndicator label="Reflecting…" size="sm" /> : "⟳ Reflect"}
        </button>
      </div>

      {reindexMsg && <p className="reflect-msg">{reindexMsg}</p>}
      {reflectMsg && <p className="reflect-msg">{reflectMsg}</p>}
      {error && <p className="topics-error">{error}</p>}

      {coreOpen && (
        <div className="topic-editor">
          <div className="topic-editor-header">
            <div>
              <strong className="topic-editor-slug">core profile</strong>
              <span className="topic-editor-desc"> — always injected (short)</span>
            </div>
            <button className="icon-btn" onClick={() => setCoreOpen(false)} title="Close" type="button">
              <Icon name="close" size={13} />
            </button>
          </div>
          <textarea
            className="topic-editor-textarea"
            value={core}
            onChange={(e) => setCore(e.target.value)}
            spellCheck={false}
            placeholder="Short identity / prefs for every chat turn…"
          />
          <div className="topic-editor-actions">
            <button className="save-topic-btn" onClick={handleSaveCore} disabled={saving} type="button">
              {saving ? <WaitingIndicator label="Saving…" size="sm" /> : "Save profile"}
            </button>
          </div>
        </div>
      )}

      {selected && !coreOpen && (
        <div className="topic-editor">
          <div className="topic-editor-header">
            <div>
              <strong className="topic-editor-slug">{selected.slug}</strong>
              {selected.description && (
                <span className="topic-editor-desc"> — {selected.description}</span>
              )}
            </div>
            <button className="icon-btn" onClick={() => setSelected(null)} title="Close" type="button">
              <Icon name="close" size={13} />
            </button>
          </div>

          <div className="memory-facts-list">
            {facts.length === 0 && (
              <p className="topics-empty">No active facts in this category yet.</p>
            )}
            {facts.map((f) => (
              <div key={f.id} className="memory-fact-row">
                {editingId === f.id ? (
                  <>
                    <textarea
                      className="memory-fact-edit"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={3}
                    />
                    <div className="memory-fact-actions">
                      <button
                        className="save-topic-btn"
                        onClick={() => handleSaveFact(f.id)}
                        disabled={saving}
                        type="button"
                      >
                        Save
                      </button>
                      <button
                        className="cancel-topic-btn"
                        onClick={() => setEditingId(null)}
                        type="button"
                      >
                        Cancel
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="memory-fact-text">{f.text}</p>
                    <div className="memory-fact-actions">
                      <button
                        className="cancel-topic-btn"
                        onClick={() => {
                          setEditingId(f.id);
                          setEditText(f.text);
                        }}
                        type="button"
                      >
                        Edit
                      </button>
                      <button
                        className="cancel-topic-btn topic-delete-btn"
                        onClick={() => handleDeleteFact(f.id)}
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="memory-fact-add">
            <textarea
              className="memory-fact-edit"
              placeholder="Add an atomic fact…"
              value={newFact}
              onChange={(e) => setNewFact(e.target.value)}
              rows={2}
            />
            <button
              className="save-topic-btn"
              onClick={handleAddFact}
              disabled={saving || !newFact.trim()}
              type="button"
            >
              Add fact
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
