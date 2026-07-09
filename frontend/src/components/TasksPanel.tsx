import { useEffect, useState } from "react";
import { type Task, createTask, deleteTask, fetchTasks, toggleTask } from "../lib/api";
import Icon from "./Icon";
import { WaitingIndicator } from "./WaitingIndicator";

const TIMES = [
  { label: "Morning",      time: "8:00 AM",  emoji: "🌅", value: "daily 08:00" },
  { label: "Lunch",        time: "12:00 PM", emoji: "☀️", value: "daily 12:00" },
  { label: "Evening",      time: "6:00 PM",  emoji: "🌆", value: "daily 18:00" },
  { label: "Before sleep", time: "10:00 PM", emoji: "🌙", value: "daily 22:00" },
];

const WEEKDAYS = [
  { label: "Mon", value: "MON" },
  { label: "Tue", value: "TUE" },
  { label: "Wed", value: "WED" },
  { label: "Thu", value: "THU" },
  { label: "Fri", value: "FRI" },
  { label: "Sat", value: "SAT" },
  { label: "Sun", value: "SUN" },
];

type ScheduleType = "daily" | "weekly" | "once";

export default function TasksPanel() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set(["daily 08:00"]));
  const [scheduleType, setScheduleType] = useState<ScheduleType>("daily");
  const [weekday, setWeekday] = useState("MON");
  const [onceAt, setOnceAt] = useState("");
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
    if (!title.trim() || !prompt.trim()) {
      setError("Title and prompt are required.");
      return;
    }
    let schedule = "";
    if (scheduleType === "daily") {
      if (selected.size === 0) {
        setError("Pick at least one time.");
        return;
      }
      schedule = TIMES.filter((t) => selected.has(t.value)).map((t) => t.value).join(",");
    } else if (scheduleType === "weekly") {
      const timeEntry = TIMES.find((t) => selected.has(t.value));
      if (!timeEntry) {
        setError("Pick a time for the weekly task.");
        return;
      }
      const time = timeEntry.value.replace("daily ", "");
      schedule = `weekly ${weekday} ${time}`;
    } else {
      if (!onceAt) {
        setError("Pick a date and time for the one-shot task.");
        return;
      }
      schedule = `once ${onceAt}`;
    }
    setSaving(true); setError("");
    try {
      await createTask(title.trim(), prompt.trim(), schedule);
      setCreating(false); setTitle(""); setPrompt("");
      setSelected(new Set(["daily 08:00"]));
      setScheduleType("daily");
      setOnceAt("");
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
          <div className="task-schedule-type">
            {(["daily", "weekly", "once"] as ScheduleType[]).map((t) => (
              <button
                key={t}
                type="button"
                className={`task-schedule-type-btn${scheduleType === t ? " task-schedule-type-btn--active" : ""}`}
                onClick={() => setScheduleType(t)}
              >
                {t === "daily" ? "Daily" : t === "weekly" ? "Weekly" : "Once"}
              </button>
            ))}
          </div>
          {scheduleType === "weekly" && (
            <div className="task-weekday-btns">
              {WEEKDAYS.map((d) => (
                <button
                  key={d.value}
                  type="button"
                  className={`task-weekday-btn${weekday === d.value ? " task-weekday-btn--active" : ""}`}
                  onClick={() => setWeekday(d.value)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          )}
          {scheduleType === "once" ? (
            <input
              type="datetime-local"
              className="task-input"
              value={onceAt}
              onChange={(e) => setOnceAt(e.target.value)}
            />
          ) : (
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
          )}
          {error && <p className="task-error">{error}</p>}
          <div className="task-form-actions">
            <button className="task-save-btn" onClick={handleCreate} disabled={saving}>
              {saving ? <WaitingIndicator label="Saving…" size="sm" /> : "Create task"}
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
