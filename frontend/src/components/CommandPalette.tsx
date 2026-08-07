import { useEffect, useMemo, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import type { SessionInfo } from "../lib/api";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  commands: Command[];
  sessions: SessionInfo[];
  onSelectSession: (id: string) => void;
}

export default function CommandPalette({ open, onClose, commands, sessions, onSelectSession }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 20);
    }
  }, [open]);

  // Build the flat list: commands first, then matching sessions.
  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cmdMatches = commands.filter((c) => !q || c.label.toLowerCase().includes(q));
    const sessionMatches: Command[] = sessions
      .filter((s) => q && s.title.toLowerCase().includes(q))
      .slice(0, 6)
      .map((s) => ({
        id: `session:${s.session_id}`,
        label: s.title || "Untitled",
        group: "Jump to chat",
        run: () => onSelectSession(s.session_id),
      }));
    return [...cmdMatches, ...sessionMatches];
  }, [query, commands, sessions, onSelectSession]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  function exec(i: number) {
    const item = items[i];
    if (!item) return;
    onClose();
    item.run();
  }

  useFocusTrap(true, panelRef);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); exec(active); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  // Group headers as we render.
  let lastGroup = "";

  return (
    <div className="cmdk-backdrop" onClick={onClose} role="presentation">
      <div
        ref={panelRef}
        className="cmdk-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          className="cmdk-input"
          placeholder="Type a command or search chats…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded="true"
          aria-controls="cmdk-listbox"
          aria-activedescendant={items[active] ? `cmdk-opt-${items[active].id}` : undefined}
          aria-autocomplete="list"
        />
        <div className="cmdk-list" id="cmdk-listbox" role="listbox">
          {items.length === 0 && <div className="cmdk-empty">No results</div>}
          {items.map((item, i) => {
            const showGroup = item.group !== lastGroup;
            lastGroup = item.group;
            return (
              <div key={item.id}>
                {showGroup && <div className="cmdk-group">{item.group}</div>}
                <div
                  id={`cmdk-opt-${item.id}`}
                  role="option"
                  aria-selected={i === active}
                  className={`cmdk-item${i === active ? " cmdk-item--active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => exec(i)}
                >
                  <span className="cmdk-item-label">{item.label}</span>
                  {item.hint && <span className="cmdk-item-hint">{item.hint}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
