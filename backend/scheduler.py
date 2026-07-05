"""Proactive task scheduler using APScheduler.
Tasks run in background, create a new session with the agent's response.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

_TZ = os.getenv("SCHEDULER_TZ", "America/Toronto")

_scheduler: BackgroundScheduler | None = None

# Schedule expression format stored in DB:
#   "daily HH:MM"          → every day at HH:MM
#   "weekly MON HH:MM"     → every Monday at HH:MM (MON/TUE/WED/THU/FRI/SAT/SUN)
#   "once YYYY-MM-DDTHH:MM" → one-shot at that ISO datetime

_WEEKDAY_MAP = {
    "MON": "mon", "TUE": "tue", "WED": "wed", "THU": "thu",
    "FRI": "fri", "SAT": "sat", "SUN": "sun",
}


_TIME_LABELS = {
    "08:00": "Morning (8:00 AM)",
    "12:00": "Lunch (12:00 PM)",
    "18:00": "Evening (6:00 PM)",
    "22:00": "Before sleep (10:00 PM)",
}

def _validate_time(time_str: str) -> bool:
    """Check if a time string is valid (HH:MM format with 00-23 hours, 00-59 minutes)."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, IndexError):
        return False


def parse_schedule(schedule: str) -> str:
    """Parse schedule string (possibly comma-separated) into human-readable description."""
    entries = [s.strip() for s in schedule.split(",") if s.strip()]
    labels = []
    for entry in entries:
        parts = entry.split()
        if parts[0] == "daily" and len(parts) >= 2:
            time_str = parts[1]
            if _validate_time(time_str):
                labels.append(_TIME_LABELS.get(time_str, time_str))
            else:
                labels.append(f"[Invalid: {time_str}]")
        elif parts[0] == "weekly" and len(parts) >= 3:
            day = parts[1].upper()
            time_str = parts[2]
            day_ok = day in _WEEKDAY_MAP
            time_ok = _validate_time(time_str)
            if day_ok and time_ok:
                labels.append(f"Every {day.capitalize()} {_TIME_LABELS.get(time_str, time_str)}")
            else:
                issues = [msg for ok, msg in ((day_ok, f"day: {day}"), (time_ok, f"time: {time_str}")) if not ok]
                labels.append(f"[Invalid weekly ({', '.join(issues)})]")
        elif parts[0] == "once" and len(parts) >= 2:
            labels.append(f"Once at {parts[1]}")
        else:
            labels.append(entry)
    return " · ".join(labels) if labels else schedule


def next_run_from_schedule(schedule: str) -> str | None:
    """Compute earliest next run datetime (UTC ISO) from schedule string (comma-separated)."""
    import zoneinfo
    tz = zoneinfo.ZoneInfo(_TZ)
    now = datetime.now(tz)
    candidates = []
    for entry in schedule.split(","):
        result = _next_run_single(entry.strip(), now)
        if result:
            candidates.append(result)
    return min(candidates) if candidates else None


def _next_run_single(schedule: str, now: datetime) -> str | None:
    parts = schedule.strip().split()

    try:
        if parts[0] == "daily" and len(parts) >= 2:
            if not _validate_time(parts[1]):
                return None
            h, m = map(int, parts[1].split(":"))
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.isoformat()

        if parts[0] == "weekly" and len(parts) >= 3:
            day = parts[1].upper()
            if day not in _WEEKDAY_MAP or not _validate_time(parts[2]):
                return None
            day = _WEEKDAY_MAP.get(day, "mon")
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
            if not _validate_time(parts[1]):
                return None
            h, m = map(int, parts[1].split(":"))
            return CronTrigger(hour=h, minute=m, timezone=_TZ)
        if parts[0] == "weekly" and len(parts) >= 3:
            day = parts[1].upper()
            if day not in _WEEKDAY_MAP or not _validate_time(parts[2]):
                return None
            day = _WEEKDAY_MAP.get(day, "mon")
            h, m = map(int, parts[2].split(":"))
            return CronTrigger(day_of_week=day, hour=h, minute=m, timezone=_TZ)
        if parts[0] == "once" and len(parts) >= 2:
            dt = datetime.fromisoformat(parts[1]).replace(tzinfo=timezone.utc)
            return DateTrigger(run_date=dt, timezone=_TZ)
    except Exception:
        pass
    return None


def _run_task(task_id: str, prompt: str, title: str) -> None:
    """Called by scheduler. Runs the agent prompt, saves to a new session."""
    from .llm import anthropic_client
    from .models import UTILITY_MODEL
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

    client = anthropic_client()
    resp = client.messages.create(
        model=UTILITY_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    save_message(session_id, "assistant", text)

    # Push notification
    try:
        from .push import send_push_to_all
        preview = text[:120] + ("…" if len(text) > 120 else "")
        send_push_to_all(title=f"[Task] {title}", body=preview, url=f"/?session={session_id}")
    except Exception:
        pass

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
    # Remove all existing jobs for this task
    for job in sched.get_jobs():
        if job.id.startswith(f"task_{task_id}_"):
            sched.remove_job(job.id)

    entries = [s.strip() for s in schedule.split(",") if s.strip()]
    for i, entry in enumerate(entries):
        trigger = _build_trigger(entry)
        if trigger:
            sched.add_job(
                _run_task,
                trigger=trigger,
                id=f"task_{task_id}_{i}",
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
    for job in sched.get_jobs():
        if job.id.startswith(f"task_{task_id}_"):
            sched.remove_job(job.id)
