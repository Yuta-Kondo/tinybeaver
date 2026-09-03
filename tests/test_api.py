"""Tests for FastAPI endpoints that don't require a real LLM."""
from fastapi.testclient import TestClient

from backend.memory import save_session, save_message, save_topic, save_task
from backend.memory_graph import FIXED_CATEGORIES, add_fact
from backend.main import app

client = TestClient(app)


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_list_sessions_empty():
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_with_data():
    save_session("s1", "Hello world")
    save_message("s1", "user", "hi")  # empty sessions are filtered out
    resp = client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "s1"
    assert data[0]["title"] == "Hello world"


def test_get_session_messages_empty():
    save_session("s1", "Test")
    resp = client.get("/sessions/s1/messages")
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


def test_get_session_messages():
    save_session("s1", "Test")
    save_message("s1", "user", "hi")
    save_message("s1", "assistant", "hello")
    resp = client.get("/sessions/s1/messages")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hi"


def test_delete_session():
    save_session("s1", "Delete me")
    resp = client.delete("/sessions/s1")
    assert resp.status_code == 200
    assert client.get("/sessions").json() == []


def test_delete_session_not_found():
    resp = client.delete("/sessions/nonexistent")
    assert resp.status_code == 404


def test_search_sessions():
    save_session("s1", "Python")
    save_message("s1", "user", "Tell me about Python decorators")
    resp = client.get("/sessions/search?q=Python")
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["session_id"] == "s1" for r in results)


def test_delete_message():
    save_session("s1", "Test")
    save_message("s1", "user", "hi")
    msgs = client.get("/sessions/s1/messages").json()["messages"]
    msg_id = msgs[0]["id"]
    resp = client.delete(f"/sessions/s1/messages/{msg_id}")
    assert resp.status_code == 200
    assert client.get("/sessions/s1/messages").json()["messages"] == []


# ── Topics ───────────────────────────────────────────────────────────────────

def test_list_topics_seeds_fixed_categories():
    """/topics lists the closed catalog, each with a zero fact count."""
    resp = client.get("/topics")
    assert resp.status_code == 200
    topics = resp.json()["topics"]
    assert {t["slug"] for t in topics} == set(FIXED_CATEGORIES)
    assert all(t["fact_count"] == 0 for t in topics)


def test_list_topics_counts_facts():
    add_fact("money", "Rent is 1500/mo")
    add_fact("money", "Groceries ~400/mo")
    topics = client.get("/topics").json()["topics"]
    money = next(t for t in topics if t["slug"] == "money")
    assert money["fact_count"] == 2


def test_list_topics_ignores_content_only_topics():
    """Topic rows without facts don't surface — content blobs are legacy."""
    save_topic("finance", "Budget notes", "Money stuff")
    topics = client.get("/topics").json()["topics"]
    assert not any(t["slug"] == "finance" for t in topics)


def test_get_topic():
    """`content` is rendered from the fact list, not the legacy content blob."""
    save_topic("career", "ignored blob", "")
    add_fact("career", "Starting a new role at Acme Corp in Sept 2026")
    resp = client.get("/topics/career")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "career"
    assert data["fact_count"] == 1
    assert data["content"] == "- Starting a new role at Acme Corp in Sept 2026"


def test_fixed_category_description_is_code_owned():
    """Descriptions on fixed categories belong to FIXED_CATEGORIES, not the DB.

    `add_fact()` calls `ensure_fixed_categories()`, which re-asserts the
    catalog description. Anything written by PUT /topics/{slug} is therefore
    reverted the next time a fact lands in that category.
    """
    save_topic("career", "", "Hand-edited description")
    assert client.get("/topics/career").json()["description"] == "Hand-edited description"

    add_fact("career", "any fact")
    assert client.get("/topics/career").json()["description"] == FIXED_CATEGORIES["career"]


def test_get_topic_not_found():
    resp = client.get("/topics/nonexistent")
    assert resp.status_code == 404


def test_update_topic_writes_description_only():
    """PUT /topics/{slug} is description-only; content blobs are never written."""
    save_topic("home", "", "Old description")
    resp = client.put(
        "/topics/home", json={"content": "ignored", "description": "New description"}
    )
    assert resp.status_code == 200
    data = client.get("/topics/home").json()
    assert data["description"] == "New description"
    assert data["content"] == ""  # no facts added, so nothing to render


def test_create_topic_via_post():
    resp = client.post("/topics/new-slug", json={"description": "A new topic"})
    assert resp.status_code == 200
    assert resp.json()["slug"] == "new-slug"
    resp2 = client.get("/topics/new-slug")
    assert resp2.status_code == 200


def test_create_topic_invalid_slug():
    resp = client.post("/topics/has space", json={})
    assert resp.status_code == 400


# ── Tasks ─────────────────────────────────────────────────────────────────────

def test_list_tasks_empty():
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert resp.json()["tasks"] == []


def test_create_task():
    resp = client.post("/tasks", json={
        "title": "Daily report",
        "prompt": "Summarize the day",
        "schedule": "daily",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data


def test_toggle_task():
    resp = client.post("/tasks", json={
        "title": "Task", "prompt": "Do something", "schedule": "daily",
    })
    task_id = resp.json()["id"]
    resp2 = client.patch(f"/tasks/{task_id}", json={"active": False})
    assert resp2.status_code == 200
    tasks = client.get("/tasks").json()["tasks"]
    t = next(t for t in tasks if t["id"] == task_id)
    assert t["active"] == 0


def test_delete_task():
    resp = client.post("/tasks", json={
        "title": "To delete", "prompt": "prompt", "schedule": "daily",
    })
    task_id = resp.json()["id"]
    resp2 = client.delete(f"/tasks/{task_id}")
    assert resp2.status_code == 200
    tasks = client.get("/tasks").json()["tasks"]
    assert not any(t["id"] == task_id for t in tasks)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "topics" in resp.json()
