import { useEffect, useState } from "react";
import { type Task, createTask, deleteTask, fetchTasks, toggleTask } from "../lib/api";

const SCHEDULE_PRESETS = [
  { label: "Daily at 09:00", value: "daily 09:00" },
  { label: "Daily at 08:00", value: "daily 08:00" },
  { label: "Weekly Mon 09:00", value: "weekly MON 09:00" },
  { label: "Weekly Fri 17:00", value: "weekly FRI 17:00" },
  { label: "Custom…", value: "custom" },
];

export default function TasksPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [schedulePreset, setSchedulePreset] = useState(SCHEDULE_PRESETS[0].value);
  const [customSchedule, setCustomSchedule] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const t = await fetchTasks().catch(() => []);
    setTasks(t);
  }

  useEffect(() => { load(); }, []);

  async function handleCreate() {
    const schedule = schedulePreset === "custom" ? customSchedule.trim() : schedulePreset;
    if (!title.trim() || !prompt.trim() || !schedule) { setError("All fields required."); return; }
    setSaving(true); setError("");
    try {
      await createTask(title.trim(), prompt.trim(), schedule);
      setCreating(false); setTitle(""); setPrompt(""); setCustomSchedule("");
      setSchedulePreset(SCHEDULE_PRESETS[0].value);
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
          <select
            className="task-schedule-select"
            value={schedulePreset}
            onChange={(e) => setSchedulePreset(e.target.value)}
          >
            {SCHEDULE_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          {schedulePreset === "custom" && (
            <input
              className="task-input"
              placeholder='e.g. "daily 14:30" or "weekly FRI 17:00"'
              value={customSchedule}
              onChange={(e) => setCustomSchedule(e.target.value)}
            />
          )}
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
              >✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
