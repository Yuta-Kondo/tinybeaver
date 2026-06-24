"""Proactive task scheduler using APScheduler.
Tasks run in background, create a new session with the agent's response.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

_scheduler: BackgroundScheduler | None = None

# Schedule expression format stored in DB:
#   "daily HH:MM"          → every day at HH:MM
#   "weekly MON HH:MM"     → every Monday at HH:MM (MON/TUE/WED/THU/FRI/SAT/SUN)
#   "once YYYY-MM-DDTHH:MM" → one-shot at that ISO datetime

_WEEKDAY_MAP = {
    "MON": "mon", "TUE": "tue", "WED": "wed", "THU": "thu",
    "FRI": "fri", "SAT": "sat", "SUN": "sun",
}


def parse_schedule(schedule: str) -> str:
    """Parse schedule string into human-readable description."""
    parts = schedule.strip().split()
    if parts[0] == "daily" and len(parts) >= 2:
        return f"Every day at {parts[1]}"
    if parts[0] == "weekly" and len(parts) >= 3:
        return f"Every {parts[1].capitalize()} at {parts[2]}"
    if parts[0] == "once" and len(parts) >= 2:
        return f"Once at {parts[1]}"
    return schedule


def next_run_from_schedule(schedule: str) -> str | None:
    """Compute next run datetime (UTC ISO) from schedule string."""
    parts = schedule.strip().split()
    now = datetime.now(timezone.utc)

    try:
        if parts[0] == "daily" and len(parts) >= 2:
            h, m = map(int, parts[1].split(":"))
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.isoformat()

        if parts[0] == "weekly" and len(parts) >= 3:
            day = _WEEKDAY_MAP.get(parts[1].upper(), "mon")
            h, m = map(int, parts[2].split(":"))
            # Find next occurrence of that weekday
            day_nums = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_wd = day_nums.get(day, 0)
            days_ahead = (target_wd - now.weekday()) % 7
            if days_ahead == 0:
                candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate <= now:
                    days_ahead = 7
            candidate = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
            return candidate.isoformat()

        if parts[0] == "once" and len(parts) >= 2:
            dt = datetime.fromisoformat(parts[1]).replace(tzinfo=timezone.utc)
            return dt.isoformat()
    except Exception:
        pass
    return None


def _build_trigger(schedule: str):
    parts = schedule.strip().split()
    try:
        if parts[0] == "daily" and len(parts) >= 2:
            h, m = map(int, parts[1].split(":"))
            return CronTrigger(hour=h, minute=m, timezone="UTC")
        if parts[0] == "weekly" and len(parts) >= 3:
            day = _WEEKDAY_MAP.get(parts[1].upper(), "mon")
            h, m = map(int, parts[2].split(":"))
            return CronTrigger(day_of_week=day, hour=h, minute=m, timezone="UTC")
        if parts[0] == "once" and len(parts) >= 2:
            dt = datetime.fromisoformat(parts[1]).replace(tzinfo=timezone.utc)
            return DateTrigger(run_date=dt, timezone="UTC")
    except Exception:
        pass
    return None


def _run_task(task_id: str, prompt: str, title: str) -> None:
    """Called by scheduler. Runs the agent prompt, saves to a new session."""
    import anthropic
    from .memory import (
        available_topics, get_api_messages, load_context, save_message,
        save_session, update_session_title, update_task_next_run, get_task,
    )
    from .classifier import classify

    session_id = str(uuid.uuid4())
    save_session(session_id)
    update_session_title(session_id, f"[Task] {title}")
    save_message(session_id, "user", prompt)

    relevant_topics, _ = classify(prompt)
    context = load_context(relevant_topics)

    system = (
        "You are Yuta's personal AI assistant. This is a proactive scheduled task — "
        "respond concisely with the requested information or action.\n"
        + (f"\n## Memory\n\n{context}" if context else "")
    )

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    save_message(session_id, "assistant", text)

    # Update next_run for recurring tasks
    task = get_task(task_id)
    if task:
        next_run = next_run_from_schedule(task["schedule"])
        if next_run:
            update_task_next_run(task_id, next_run)


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    """Load all active tasks from DB and start the scheduler."""
    from .memory import list_tasks
    sched = get_scheduler()

    tasks = list_tasks()
    for task in tasks:
        if task["active"] and task["next_run"]:
            _schedule_task(task["id"], task["prompt"], task["title"], task["schedule"])

    if not sched.running:
        sched.start()


def _schedule_task(task_id: str, prompt: str, title: str, schedule: str) -> None:
    sched = get_scheduler()
    job_id = f"task_{task_id}"
    # Remove existing job if any
    if sched.get_job(job_id):
        sched.remove_job(job_id)

    trigger = _build_trigger(schedule)
    if trigger:
        sched.add_job(
            _run_task,
            trigger=trigger,
            id=job_id,
            args=[task_id, prompt, title],
            replace_existing=True,
            misfire_grace_time=300,
        )


def add_task_to_scheduler(task_id: str, prompt: str, title: str, schedule: str) -> None:
    if not get_scheduler().running:
        get_scheduler().start()
    _schedule_task(task_id, prompt, title, schedule)


def remove_task_from_scheduler(task_id: str) -> None:
    sched = get_scheduler()
    job_id = f"task_{task_id}"
    if sched.get_job(job_id):
        sched.remove_job(job_id)
