import { useEffect, useState } from "react";
import { type Task, createTask, deleteTask, fetchTasks, toggleTask } from "../lib/api";
import Icon from "./Icon";

const TIMES = [
  { label: "Morning",      time: "8:00 AM",  emoji: "🌅", value: "daily 08:00" },
  { label: "Lunch",        time: "12:00 PM", emoji: "☀️", value: "daily 12:00" },
  { label: "Evening",      time: "6:00 PM",  emoji: "🌆", value: "daily 18:00" },
  { label: "Before sleep", time: "10:00 PM", emoji: "🌙", value: "daily 22:00" },
];

export default function TasksPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set(["daily 08:00"]));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const t = await fetchTasks().catch(() => []);
    setTasks(t);
  }

  useEffect(() => { load(); }, []);

  function toggleTime(value: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(value)) {
        if (next.size > 1) next.delete(value); // keep at least one
      } else {
        next.add(value);
      }
      return next;
    });
  }

  async function handleCreate() {
    if (!title.trim() || !prompt.trim() || selected.size === 0) {
      setError("Title, prompt, and at least one time required.");
      return;
    }
    // Join selected schedules in order
    const schedule = TIMES.filter((t) => selected.has(t.value)).map((t) => t.value).join(",");
    setSaving(true); setError("");
    try {
      await createTask(title.trim(), prompt.trim(), schedule);
      setCreating(false); setTitle(""); setPrompt("");
      setSelected(new Set(["daily 08:00"]));
      await load();
    } catch (e: any) {
      setError(e.message ?? "Failed to create task");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(id: string, active: number) {
    await toggleTask(id, !active);
    await load();
  }

  async function handleDelete(id: string) {
    await deleteTask(id);
    await load();
  }

  function formatNextRun(next: string | null) {
    if (!next) return "—";
    try {
      return new Date(next).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch { return next; }
  }

  return (
    <div className="tasks-panel">
      <div className="tasks-header">
        <span className="tasks-count">{tasks.length} task{tasks.length !== 1 ? "s" : ""}</span>
        <button className="tasks-add-btn" onClick={() => { setCreating(true); setError(""); }}>+ New</button>
      </div>

      {creating && (
        <div className="task-form">
          <input
            className="task-input"
            placeholder="Title (e.g. Morning briefing)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
          <textarea
            className="task-prompt-input"
            placeholder="Prompt the agent will run…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
          />
          <div className="task-time-btns">
            {TIMES.map((t) => (
              <button
                key={t.value}
                className={`task-time-btn${selected.has(t.value) ? " task-time-btn--active" : ""}`}
                onClick={() => toggleTime(t.value)}
                type="button"
              >
                <span className="task-time-emoji">{t.emoji}</span>
                <span className="task-time-label">{t.label}</span>
                <span className="task-time-clock">{t.time}</span>
              </button>
            ))}
          </div>
          {error && <p className="task-error">{error}</p>}
          <div className="task-form-actions">
            <button className="task-save-btn" onClick={handleCreate} disabled={saving}>
              {saving ? "Saving…" : "Create task"}
            </button>
            <button className="task-cancel-btn" onClick={() => { setCreating(false); setError(""); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="task-list">
        {tasks.length === 0 && !creating && (
          <p className="tasks-empty">No scheduled tasks yet.<br />Tasks run in background and create new sessions.</p>
        )}
        {tasks.map((t) => (
          <div key={t.id} className={`task-item ${!t.active ? "task-item--inactive" : ""}`}>
            <div className="task-item-main">
              <span className="task-title">{t.title}</span>
              <span className="task-schedule-label">{t.schedule_label}</span>
              <span className="task-next-run">Next: {formatNextRun(t.next_run)}</span>
            </div>
            <div className="task-item-actions">
              <button
                className={`task-toggle-btn ${t.active ? "task-toggle-btn--on" : ""}`}
                onClick={() => handleToggle(t.id, t.active)}
                title={t.active ? "Disable" : "Enable"}
              >
                {t.active ? "On" : "Off"}
              </button>
              <button
                className="task-delete-btn"
                onClick={() => handleDelete(t.id)}
                title="Delete task"
              ><Icon name="trash" size={13} /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
