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

function labelFor(slug: string): string {
  if (slug === "core") return "Core profile";
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

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
  const [reindexing, setReindexing] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [loadingSlug, setLoadingSlug] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const factsScrollRef = useRef<HTMLDivElement>(null);

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

  function clearDetail() {
    setSelected(null);
    setCoreOpen(false);
    setEditingId(null);
    setNewFact("");
  }

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
      requestAnimationFrame(() => {
        factsScrollRef.current?.scrollTo({ top: 0 });
      });
    } catch {
      setError("Failed to load category.");
    } finally {
      setLoadingSlug(null);
    }
  }

  async function handleReflect() {
    setReflecting(true);
    setStatus("");
    setError("");
    try {
      const updated = await reflect();
      setStatus(
        updated.length
          ? `Consolidated: ${updated.join(", ")}`
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
    setStatus("");
    setError("");
    try {
      const count = await reindexTopics();
      setStatus(`Re-embedded ${count} fact${count === 1 ? "" : "s"}.`);
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
      setStatus("Core profile saved.");
    } catch {
      setError("Could not save core profile.");
    } finally {
      setSaving(false);
    }
  }

  const inDetail = coreOpen || selected != null;

  const displayList = searchResults
    ? searchResults.map((r) => ({
        slug: r.slug,
        description: r.snippet,
        fact_count: undefined as number | undefined,
      }))
    : topics;

  return (
    <div className={`mem-panel${inDetail ? " mem-panel--detail" : ""}`}>
      {!inDetail && (
        <>
          <div className="mem-toolbar">
            <input
              type="search"
              placeholder="Search facts…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="mem-search"
              aria-label="Search memory facts"
            />
          </div>

          <div className="mem-browse">
            <button
              className="mem-cat"
              onClick={() => {
                setCoreOpen(true);
                setSelected(null);
              }}
              type="button"
            >
              <span className="mem-cat-main">
                <span className="mem-cat-name">Core profile</span>
                <span className="mem-cat-desc">Always on in every chat</span>
              </span>
              <span className="mem-cat-badge mem-cat-badge--muted" title="Pinned identity block">
                pinned
              </span>
            </button>

            {searching && (
              <div className="mem-busy">
                <WaitingIndicator label="Searching…" size="sm" />
              </div>
            )}
            {!searching && displayList.length === 0 && query && (
              <p className="mem-empty">No results for “{query}”</p>
            )}
            {displayList.map((t) => (
              <button
                key={t.slug + (t.description || "")}
                className={`mem-cat${loadingSlug === t.slug ? " mem-cat--loading" : ""}`}
                onClick={() => openTopic(t.slug)}
                type="button"
              >
                <span className="mem-cat-main">
                  <span className="mem-cat-name">{labelFor(t.slug)}</span>
                  {t.description && (
                    <span className="mem-cat-desc">
                      {t.description.replace(/\*\*/g, "")}
                    </span>
                  )}
                </span>
                {typeof t.fact_count === "number" && (
                  <span
                    className="mem-cat-badge"
                    title={`${t.fact_count} active fact${t.fact_count === 1 ? "" : "s"} in this category`}
                  >
                    {t.fact_count}
                    <span className="mem-cat-badge-unit">facts</span>
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="mem-footer">
            <button
              className="mem-tool"
              onClick={handleReindex}
              disabled={reindexing}
              title="Rebuild search embeddings for all facts"
              type="button"
            >
              {reindexing ? "Reindexing…" : "Reindex"}
            </button>
            <button
              className="mem-tool"
              onClick={handleReflect}
              disabled={reflecting}
              title="Merge duplicates and clean the knowledge graph"
              type="button"
            >
              {reflecting ? "Reflecting…" : "Reflect"}
            </button>
          </div>
        </>
      )}

      {(status || error) && !inDetail && (
        <p className={error ? "mem-toast mem-toast--err" : "mem-toast"}>{error || status}</p>
      )}

      {coreOpen && (
        <div className="mem-detail">
          <header className="mem-detail-head">
            <button className="mem-back" onClick={clearDetail} type="button" aria-label="Back">
              ←
            </button>
            <div className="mem-detail-titles">
              <h3 className="mem-detail-title">Core profile</h3>
              <p className="mem-detail-sub">Short identity block injected every turn</p>
            </div>
          </header>
          <div className="mem-detail-body">
            <textarea
              className="mem-textarea"
              value={core}
              onChange={(e) => setCore(e.target.value)}
              spellCheck={false}
              placeholder="Who you are, lasting prefs…"
            />
          </div>
          <footer className="mem-detail-foot">
            {(error || status) && (
              <p className={error ? "mem-toast mem-toast--err" : "mem-toast"}>{error || status}</p>
            )}
            <button className="mem-btn mem-btn--primary" onClick={handleSaveCore} disabled={saving} type="button">
              {saving ? "Saving…" : "Save"}
            </button>
          </footer>
        </div>
      )}

      {selected && !coreOpen && (
        <div className="mem-detail">
          <header className="mem-detail-head">
            <button className="mem-back" onClick={clearDetail} type="button" aria-label="Back">
              ←
            </button>
            <div className="mem-detail-titles">
              <h3 className="mem-detail-title">{labelFor(selected.slug)}</h3>
              {selected.description && (
                <p className="mem-detail-sub">{selected.description}</p>
              )}
            </div>
            <span
              className="mem-cat-badge"
              title={`${facts.length} active fact${facts.length === 1 ? "" : "s"}`}
            >
              {facts.length}
              <span className="mem-cat-badge-unit">facts</span>
            </span>
          </header>

          <div className="mem-detail-body" ref={factsScrollRef}>
            {facts.length === 0 && (
              <p className="mem-empty">No facts here yet. Add one below.</p>
            )}
            {facts.map((f) => (
              <article key={f.id} className="mem-fact">
                {editingId === f.id ? (
                  <>
                    <textarea
                      className="mem-textarea mem-textarea--compact"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={3}
                    />
                    <div className="mem-fact-actions">
                      <button
                        className="mem-btn mem-btn--primary"
                        onClick={() => handleSaveFact(f.id)}
                        disabled={saving}
                        type="button"
                      >
                        Save
                      </button>
                      <button className="mem-btn" onClick={() => setEditingId(null)} type="button">
                        Cancel
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="mem-fact-text">{f.text}</p>
                    <div className="mem-fact-actions">
                      <button
                        className="mem-btn"
                        onClick={() => {
                          setEditingId(f.id);
                          setEditText(f.text);
                        }}
                        type="button"
                      >
                        Edit
                      </button>
                      <button
                        className="mem-btn mem-btn--danger"
                        onClick={() => handleDeleteFact(f.id)}
                        type="button"
                      >
                        Remove
                      </button>
                    </div>
                  </>
                )}
              </article>
            ))}
          </div>

          <footer className="mem-detail-foot mem-detail-foot--stack">
            {(error || status) && (
              <p className={error ? "mem-toast mem-toast--err" : "mem-toast"}>{error || status}</p>
            )}
            <textarea
              className="mem-textarea mem-textarea--compact"
              placeholder="Add an atomic fact…"
              value={newFact}
              onChange={(e) => setNewFact(e.target.value)}
              rows={2}
            />
            <button
              className="mem-btn mem-btn--primary"
              onClick={handleAddFact}
              disabled={saving || !newFact.trim()}
              type="button"
            >
              Add fact
            </button>
          </footer>
        </div>
      )}
    </div>
  );
}
