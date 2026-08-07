import { useMemo, useState } from "react";
import type { Message } from "../hooks/useChat";
import Icon from "./Icon";

/** A topic seen in this conversation, with how it was used. */
type RailTopic = {
  slug: string;
  loaded: number;
  updated: number;
  /** Index of the last turn that touched it — drives the "this turn" marker. */
  lastTurn: number;
};

/**
 * The right rail answers a question the chat log cannot: *what does it
 * currently know about me, and what did it just learn?* Topic memory is the
 * thing that makes this app not-a-chatbot, and until now it was only visible
 * as small tags buried under individual replies.
 *
 * Derived entirely from messages already in state — no extra fetches.
 */
export default function ContextRail({
  messages,
  open,
  onToggle,
}: {
  messages: Message[];
  open: boolean;
  onToggle: () => void;
}) {
  const [collapsedHint, setCollapsedHint] = useState(false);

  const { topics, lastTurn } = useMemo(() => {
    const map = new Map<string, RailTopic>();
    let turn = 0;
    for (const m of messages) {
      if (m.role === "assistant") turn++;
      const bump = (slug: string, key: "loaded" | "updated") => {
        const cur = map.get(slug) ?? { slug, loaded: 0, updated: 0, lastTurn: turn };
        cur[key] += 1;
        cur.lastTurn = turn;
        map.set(slug, cur);
      };
      m.loadedTopics?.forEach((t) => bump(t, "loaded"));
      m.updatedTopics?.forEach((t) => bump(t, "updated"));
    }
    // Written-to first, then most recently used, then most used.
    const list = [...map.values()].sort(
      (a, b) =>
        b.updated - a.updated ||
        b.lastTurn - a.lastTurn ||
        b.loaded + b.updated - (a.loaded + a.updated)
    );
    return { topics: list, lastTurn: turn };
  }, [messages]);

  function openMemoryTab(slug: string) {
    window.dispatchEvent(new CustomEvent("open-sidebar-tab", { detail: "memory" }));
    window.dispatchEvent(new CustomEvent("focus-topic", { detail: slug }));
  }

  if (!open) {
    return (
      <button
        className="rail-reopen"
        onClick={onToggle}
        title="Show memory in play"
        aria-label="Show memory in play"
        onMouseEnter={() => setCollapsedHint(true)}
        onMouseLeave={() => setCollapsedHint(false)}
      >
        <Icon name="memory" size={15} />
        {topics.length > 0 && <span className="rail-reopen-count">{topics.length}</span>}
        {collapsedHint && <span className="rail-reopen-hint">Memory</span>}
      </button>
    );
  }

  return (
    <aside className="context-rail" aria-label="Memory in play">
      <div className="rail-head">
        <span className="rail-title">Memory in play</span>
        <button className="rail-collapse" onClick={onToggle} title="Hide" aria-label="Hide memory rail">
          <Icon name="close" size={13} />
        </button>
      </div>

      {topics.length === 0 ? (
        <p className="rail-empty">
          No topics loaded yet. Ask something personal and the topics it pulls
          into context will appear here.
        </p>
      ) : (
        <ul className="rail-list">
          {topics.map((t) => {
            const isThisTurn = t.lastTurn === lastTurn && lastTurn > 0;
            return (
              <li key={t.slug}>
                <button
                  className={`rail-topic${t.updated > 0 ? " rail-topic--written" : ""}${
                    isThisTurn ? " rail-topic--active" : ""
                  }`}
                  onClick={() => openMemoryTab(t.slug)}
                  title={
                    t.updated > 0
                      ? `${t.slug} — loaded ${t.loaded}×, written ${t.updated}×`
                      : `${t.slug} — loaded ${t.loaded}×`
                  }
                >
                  <span className="rail-topic-slug">{t.slug}</span>
                  <span className="rail-topic-meta">
                    {t.updated > 0 && (
                      <span className="rail-badge rail-badge--written" title="Written to memory">
                        ✦{t.updated > 1 ? t.updated : ""}
                      </span>
                    )}
                    {t.loaded > 0 && <span className="rail-badge">{t.loaded}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="rail-foot">
        <span className="rail-foot-key">
          <span className="rail-badge rail-badge--written">✦</span> written
        </span>
        <span className="rail-foot-key">
          <span className="rail-badge">n</span> loads
        </span>
      </div>
    </aside>
  );
}
