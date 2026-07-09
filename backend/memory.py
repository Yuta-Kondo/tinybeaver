from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "memory.db"
_LEGACY_DIR = Path(__file__).parent.parent / "memory"

_conn: sqlite3.Connection | None = None
_conn_lock = threading.Lock()

_INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS topics (
    slug        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    embedding   BLOB,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
    content,
    content=topics,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS topics_ai AFTER INSERT ON topics BEGIN
    INSERT INTO topics_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS topics_ad AFTER DELETE ON topics BEGIN
    INSERT INTO topics_fts(topics_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS topics_au AFTER UPDATE ON topics BEGIN
    INSERT INTO topics_fts(topics_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO topics_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT '',
    summary           TEXT NOT NULL DEFAULT '',
    summary_msg_count INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    schedule    TEXT NOT NULL DEFAULT 'daily',
    next_run    TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider    TEXT PRIMARY KEY,
    token_json  TEXT NOT NULL,
    email       TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          TEXT PRIMARY KEY,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Migration: add columns that may not exist in older DBs
_MIGRATIONS = [
    "ALTER TABLE topics ADD COLUMN embedding BLOB",
    "ALTER TABLE tasks ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'))",
    "ALTER TABLE messages ADD COLUMN moa_drafts TEXT",
    "ALTER TABLE messages ADD COLUMN model TEXT",
    "ALTER TABLE messages ADD COLUMN cost_usd REAL",
    "ALTER TABLE messages ADD COLUMN cost_breakdown TEXT",
    "ALTER TABLE messages ADD COLUMN attachments TEXT",
]


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _conn_lock:
            if _conn is None:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA busy_timeout=5000")
                c.executescript(_INIT_SQL)
                _run_migrations(c)
                _migrate_legacy(c)
                _conn = c
    return _conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] > 0:
        return
    if not _LEGACY_DIR.exists():
        return

    descriptions: dict[str, str] = {}
    index_path = _LEGACY_DIR / "index.md"
    if index_path.exists():
        for line in index_path.read_text("utf-8").splitlines():
            if "—" in line and "[" in line:
                try:
                    slug = line[line.index("[") + 1 : line.index("]")]
                    desc = line.split("—", 1)[1].strip()
                    descriptions[slug] = desc
                except (ValueError, IndexError):
                    pass

    for md in _LEGACY_DIR.glob("*.md"):
        if md.stem == "index":
            continue
        conn.execute(
            "INSERT OR IGNORE INTO topics (slug, description, content) VALUES (?, ?, ?)",
            (md.stem, descriptions.get(md.stem, ""), md.read_text("utf-8")),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Topics API
# ---------------------------------------------------------------------------

def available_topics() -> list[str]:
    return [r[0] for r in _get_conn().execute("SELECT slug FROM topics ORDER BY slug")]


def topic_descriptions() -> dict[str, str]:
    rows = _get_conn().execute("SELECT slug, description FROM topics ORDER BY slug").fetchall()
    return {r[0]: r[1] for r in rows}


def get_topics_content(slugs: list[str]) -> dict[str, str]:
    conn = _get_conn()
    result: dict[str, str] = {}
    for slug in slugs:
        row = conn.execute("SELECT content FROM topics WHERE slug = ?", (slug,)).fetchone()
        result[slug] = row[0] if row else ""
    return result


def load_context(topics: list[str]) -> str:
    parts = []
    for slug, content in get_topics_content(topics).items():
        if content.strip():
            parts.append(f"### {slug.capitalize()}\n{content.strip()}")
    return "\n\n".join(parts)


def save_topic(slug: str, content: str, description: str = "") -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO topics (slug, description, content, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(slug) DO UPDATE SET
            content     = excluded.content,
            description = CASE WHEN excluded.description != ''
                               THEN excluded.description ELSE description END,
            updated_at  = datetime('now')
        """,
        (slug, description, content),
    )
    conn.commit()


def save_topic_embedding(slug: str, embedding_bytes: bytes) -> None:
    _get_conn().execute(
        "UPDATE topics SET embedding = ? WHERE slug = ?", (embedding_bytes, slug)
    )
    _get_conn().commit()


def get_all_topic_embeddings() -> list[dict]:
    rows = _get_conn().execute(
        "SELECT slug, description, content, embedding FROM topics"
    ).fetchall()
    return [dict(r) for r in rows]


def create_topic(slug: str, description: str = "") -> None:
    if not slug.replace("-", "").isalnum() or slug == "index":
        raise ValueError(f"Invalid topic slug: {slug!r}")
    _get_conn().execute(
        "INSERT OR IGNORE INTO topics (slug, description, content) VALUES (?, ?, '')",
        (slug, description),
    )
    _get_conn().commit()


def delete_topic(slug: str) -> None:
    _get_conn().execute("DELETE FROM topics WHERE slug = ?", (slug,))
    _get_conn().commit()


def get_topic(slug: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT slug, description, content, updated_at FROM topics WHERE slug = ?", (slug,)
    ).fetchone()
    return dict(row) if row else None


def search_topics(query: str, limit: int = 8) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT t.slug,
                   snippet(topics_fts, 0, '**', '**', '...', 20) AS snip
            FROM   topics_fts
            JOIN   topics t ON t.rowid = topics_fts.rowid
            WHERE  topics_fts MATCH ?
            ORDER  BY rank
            LIMIT  ?
            """,
            (query, limit),
        ).fetchall()
        return [{"slug": r[0], "snippet": r[1]} for r in rows]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# Sessions API
# ---------------------------------------------------------------------------

def save_session(session_id: str, title: str = "") -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO sessions (session_id, title)
        VALUES (?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            title      = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,
            updated_at = datetime('now')
        """,
        (session_id, title),
    )
    conn.commit()


def get_session(session_id: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT session_id, title, summary, summary_msg_count, created_at, updated_at "
        "FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    rows = _get_conn().execute(
        """
        SELECT s.session_id, s.title, s.updated_at, COUNT(m.id) AS message_count
        FROM   sessions s
        LEFT JOIN messages m ON m.session_id = s.session_id
        GROUP  BY s.session_id
        ORDER  BY s.updated_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def search_sessions(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all messages, returns matching sessions with snippets."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT m.session_id,
                   s.title,
                   snippet(messages_fts, 0, '**', '**', '...', 25) AS snip
            FROM   messages_fts
            JOIN   messages m  ON m.id = messages_fts.rowid
            JOIN   sessions s  ON s.session_id = m.session_id
            WHERE  messages_fts MATCH ?
            ORDER  BY rank
            LIMIT  ?
            """,
            (query, limit),
        ).fetchall()
        return [{"session_id": r[0], "title": r[1] or "New conversation", "snippet": r[2]} for r in rows]
    except sqlite3.OperationalError:
        return []


def delete_session_db(session_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    return cur.rowcount > 0


def update_session_title(session_id: str, title: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = datetime('now') WHERE session_id = ?",
        (title, session_id),
    )
    conn.commit()


def update_session_summary(session_id: str, summary: str, through_count: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET summary = ?, summary_msg_count = ?, updated_at = datetime('now') "
        "WHERE session_id = ?",
        (summary, through_count, session_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Messages API
# ---------------------------------------------------------------------------

def save_message(
    session_id: str,
    role: str,
    content: str | list,
    moa_drafts: list | None = None,
    attachments: list | None = None,
) -> int:
    stored = content if isinstance(content, str) else json.dumps(content)
    drafts_json = json.dumps(moa_drafts) if moa_drafts else None
    attachments_json = json.dumps(attachments) if attachments else None
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO messages (session_id, role, content, moa_drafts, attachments) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, stored, drafts_json, attachments_json),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = datetime('now') WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_message_meta(msg_id: int, model: str, cost_usd: float, cost_breakdown: dict | None = None) -> None:
    """Record which model produced an assistant reply and what it cost, so the
    info survives a session reload."""
    _get_conn().execute(
        "UPDATE messages SET model = ?, cost_usd = ?, cost_breakdown = ? WHERE id = ?",
        (model, cost_usd, json.dumps(cost_breakdown) if cost_breakdown else None, msg_id),
    )
    _get_conn().commit()


def get_messages(session_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT id, role, content, moa_drafts, model, cost_usd, cost_breakdown, attachments FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    result = []
    for r in rows:
        content = r["content"]
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                text = " ".join(
                    b.get("text", "") for b in parsed if isinstance(b, dict) and b.get("type") == "text"
                )
                content = text or content
        except (json.JSONDecodeError, TypeError):
            pass
        moa_drafts = None
        if r["moa_drafts"]:
            try:
                moa_drafts = json.loads(r["moa_drafts"])
            except (json.JSONDecodeError, TypeError):
                pass
        cost_breakdown = None
        if r["cost_breakdown"]:
            try:
                cost_breakdown = json.loads(r["cost_breakdown"])
            except (json.JSONDecodeError, TypeError):
                pass
        attachments = None
        if r["attachments"]:
            try:
                attachments = json.loads(r["attachments"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append({
            "id": r["id"], "role": r["role"], "content": content, "moa_drafts": moa_drafts,
            "model": r["model"], "cost_usd": r["cost_usd"], "cost_breakdown": cost_breakdown,
            "attachments": attachments,
        })
    return result


def get_api_messages(session_id: str) -> tuple[list[dict], str]:
    session = get_session(session_id)
    if not session:
        return [], ""

    msgs = get_messages(session_id)
    summary = session["summary"]
    summary_count = session["summary_msg_count"]

    relevant = msgs[summary_count:]
    if len(relevant) > 30:
        relevant = relevant[-30:]

    api_msgs = [{"role": m["role"], "content": m["content"]} for m in relevant]
    return api_msgs, summary


def edit_message(session_id: str, msg_id: int, new_content: str) -> bool:
    """Edit a message and delete all subsequent messages in the session."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM messages WHERE id = ? AND session_id = ?", (msg_id, session_id)
    ).fetchone()
    if not row:
        return False
    conn.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, msg_id))
    conn.execute(
        "DELETE FROM messages WHERE session_id = ? AND id > ?", (session_id, msg_id)
    )
    conn.commit()
    return True


def delete_message(session_id: str, msg_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM messages WHERE id = ? AND session_id = ?", (msg_id, session_id)
    )
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Tasks API
# ---------------------------------------------------------------------------

def save_task(task_id: str, title: str, prompt: str, schedule: str, next_run: str | None) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO tasks (id, title, prompt, schedule, next_run, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            title    = excluded.title,
            prompt   = excluded.prompt,
            schedule = excluded.schedule,
            next_run = excluded.next_run
        """,
        (task_id, title, prompt, schedule, next_run),
    )
    conn.commit()


def list_tasks() -> list[dict]:
    rows = _get_conn().execute(
        "SELECT id, title, prompt, schedule, next_run, active, created_at FROM tasks ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_task(task_id: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT id, title, prompt, schedule, next_run, active FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def toggle_task(task_id: str, active: bool) -> None:
    _get_conn().execute("UPDATE tasks SET active = ? WHERE id = ?", (int(active), task_id))
    _get_conn().commit()


def update_task_next_run(task_id: str, next_run: str) -> None:
    _get_conn().execute("UPDATE tasks SET next_run = ? WHERE id = ?", (next_run, task_id))
    _get_conn().commit()


def delete_task(task_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    return cur.rowcount > 0


# ── OAuth token storage ───────────────────────────────────────────────────────

def save_oauth_token(provider: str, token_json: str, email: str = "") -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT INTO oauth_tokens (provider, token_json, email, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(provider) DO UPDATE SET
               token_json = excluded.token_json,
               email      = excluded.email,
               updated_at = excluded.updated_at""",
        (provider, token_json, email),
    )
    conn.commit()


def load_oauth_token(provider: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT token_json, email FROM oauth_tokens WHERE provider = ?", (provider,)
    ).fetchone()
    if not row:
        return None
    return {"token_json": row["token_json"], "email": row["email"]}


def delete_oauth_token(provider: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM oauth_tokens WHERE provider = ?", (provider,))
    conn.commit()


# ── Push subscriptions ────────────────────────────────────────────────────────

def save_push_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    import uuid
    conn = _get_conn()
    conn.execute(
        """INSERT INTO push_subscriptions (id, endpoint, p256dh, auth)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               p256dh = excluded.p256dh,
               auth   = excluded.auth""",
        (str(uuid.uuid4()), endpoint, p256dh, auth),
    )
    conn.commit()


def list_push_subscriptions() -> list[dict]:
    rows = _get_conn().execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_push_subscription(endpoint: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
