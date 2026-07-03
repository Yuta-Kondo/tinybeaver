"""Tests for FastAPI endpoints that don't require a real LLM."""
from fastapi.testclient import TestClient

from backend.memory import save_session, save_message, save_topic, save_task
from backend.main import app

client = TestClient(app)


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_list_sessions_empty():
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_with_data():
    save_session("s1", "Hello world")
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

def test_list_topics_empty():
    resp = client.get("/topics")
    assert resp.status_code == 200
    assert resp.json()["topics"] == []


def test_list_topics():
    save_topic("finance", "Budget notes", "Money stuff")
    resp = client.get("/topics")
    assert resp.status_code == 200
    topics = resp.json()["topics"]
    assert any(t["slug"] == "finance" for t in topics)


def test_get_topic():
    save_topic("phd", "Research at McMaster", "PhD notes")
    resp = client.get("/topics/phd")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "phd"
    assert data["content"] == "Research at McMaster"
    assert data["description"] == "PhD notes"


def test_get_topic_not_found():
    resp = client.get("/topics/nonexistent")
    assert resp.status_code == 404


def test_update_topic():
    save_topic("housing", "Old content")
    resp = client.put("/topics/housing", json={"content": "New content", "description": ""})
    assert resp.status_code == 200
    resp2 = client.get("/topics/housing")
    assert resp2.json()["content"] == "New content"


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
