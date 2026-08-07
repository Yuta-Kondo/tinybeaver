import pytest
from backend.memory import (
    available_topics,
    create_topic,
    delete_message,
    delete_session_db,
    delete_task,
    edit_message,
    get_api_messages,
    get_messages,
    get_session,
    get_task,
    get_topic,
    list_sessions,
    list_tasks,
    save_message,
    save_session,
    save_task,
    save_topic,
    search_sessions,
    search_topics,
    toggle_task,
    topic_descriptions,
)

# Note: save_topic signature is (slug, content, description="")


# ── Topics ───────────────────────────────────────────────────────────────────

def test_save_and_get_topic():
    save_topic("housing", "Looking for 1BR", "Housing search notes")
    t = get_topic("housing")
    assert t is not None
    assert t["slug"] == "housing"
    assert t["content"] == "Looking for 1BR"
    assert t["description"] == "Housing search notes"


def test_save_topic_upsert_content():
    save_topic("housing", "v1", "desc1")
    save_topic("housing", "v2", "")  # blank description should not overwrite
    t = get_topic("housing")
    assert t["content"] == "v2"
    assert t["description"] == "desc1"


def test_available_topics_seeds_fixed_catalog():
    """A fresh DB is not empty: the closed category catalog is seeded on init.

    `_get_conn()` calls `ensure_fixed_categories()`, so every database starts
    with the fixed taxonomy. This asserted `== []` back when categories were
    open-ended and created on demand.
    """
    from backend.memory_graph import FIXED_CATEGORIES

    assert available_topics() == sorted(FIXED_CATEGORIES)


def test_available_topics_sorted():
    save_topic("zebra", "z")
    save_topic("alpha", "a")
    topics = available_topics()
    assert topics == sorted(topics)
    assert {"alpha", "zebra"} <= set(topics)


def test_topic_descriptions():
    save_topic("finance", "Money content", "Money stuff")
    descs = topic_descriptions()
    assert descs["finance"] == "Money stuff"


def test_create_topic_invalid_slug():
    with pytest.raises(ValueError):
        create_topic("has space")
    with pytest.raises(ValueError):
        create_topic("index")
    with pytest.raises(ValueError):
        create_topic("has/slash")


def test_create_topic_no_duplicate():
    create_topic("new-topic")
    create_topic("new-topic")  # should not raise
    assert available_topics().count("new-topic") == 1


def test_search_topics():
    save_topic("phd", "PhD research at McMaster university")
    save_topic("finance", "Monthly budget and savings")
    results = search_topics("McMaster")
    slugs = [r["slug"] for r in results]
    assert "phd" in slugs
    assert "finance" not in slugs


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_save_and_get_session():
    save_session("sess-1", "My chat")
    s = get_session("sess-1")
    assert s is not None
    assert s["session_id"] == "sess-1"
    assert s["title"] == "My chat"


def test_save_session_upsert_title():
    save_session("sess-1", "First title")
    save_session("sess-1", "")  # blank should not overwrite
    assert get_session("sess-1")["title"] == "First title"
    save_session("sess-1", "Updated")
    assert get_session("sess-1")["title"] == "Updated"


def test_list_sessions_ordered():
    # list_sessions() filters on HAVING COUNT(messages) > 0, so a session with
    # no messages is deliberately invisible — see test below.
    save_session("a", "A")
    save_message("a", "user", "hi")
    save_session("b", "B")
    save_message("b", "user", "hi")
    sessions = list_sessions()
    ids = [s["session_id"] for s in sessions]
    assert "a" in ids and "b" in ids


def test_list_sessions_hides_empty_sessions():
    """An unused "New chat" should not clutter the sidebar."""
    save_session("ghost", "Never used")
    assert get_session("ghost") is not None
    assert "ghost" not in [s["session_id"] for s in list_sessions()]


def test_delete_session():
    save_session("sess-del", "To delete")
    assert delete_session_db("sess-del") is True
    assert get_session("sess-del") is None
    assert delete_session_db("sess-del") is False  # already gone


def test_session_message_count():
    save_session("sess-c", "Count test")
    save_message("sess-c", "user", "hello")
    save_message("sess-c", "assistant", "hi")
    sessions = list_sessions()
    s = next(s for s in sessions if s["session_id"] == "sess-c")
    assert s["message_count"] == 2


# ── Messages ─────────────────────────────────────────────────────────────────

def test_save_and_get_messages():
    save_session("sess-m", "Msgs")
    save_message("sess-m", "user", "Hello")
    save_message("sess-m", "assistant", "Hi there")
    msgs = get_messages("sess-m")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello"
    assert msgs[1]["role"] == "assistant"


def test_edit_message_truncates():
    save_session("sess-e", "Edit")
    save_message("sess-e", "user", "msg1")
    save_message("sess-e", "assistant", "reply1")
    save_message("sess-e", "user", "msg2")
    msgs = get_messages("sess-e")
    first_id = msgs[0]["id"]
    edit_message("sess-e", first_id, "edited")
    msgs = get_messages("sess-e")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "edited"


def test_delete_message():
    save_session("sess-d", "Del msg")
    save_message("sess-d", "user", "keep")
    save_message("sess-d", "assistant", "remove")
    msgs = get_messages("sess-d")
    remove_id = msgs[1]["id"]
    assert delete_message("sess-d", remove_id) is True
    assert len(get_messages("sess-d")) == 1


def test_delete_messages_cascade_with_session():
    save_session("sess-cas", "Cascade")
    save_message("sess-cas", "user", "hello")
    delete_session_db("sess-cas")
    assert get_messages("sess-cas") == []


def test_get_api_messages_summary_windowing():
    save_session("sess-api", "API")
    for i in range(5):
        save_message("sess-api", "user", f"msg{i}")
    msgs, summary = get_api_messages("sess-api")
    assert len(msgs) == 5
    assert summary == ""


def test_search_sessions():
    save_session("sess-s1", "Python chat")
    save_message("sess-s1", "user", "Tell me about Python decorators")
    save_session("sess-s2", "JS chat")
    save_message("sess-s2", "user", "Explain JavaScript closures")
    results = search_sessions("Python")
    ids = [r["session_id"] for r in results]
    assert "sess-s1" in ids
    assert "sess-s2" not in ids


# ── Tasks ─────────────────────────────────────────────────────────────────────

def test_save_and_get_task():
    save_task("t1", "Daily report", "Summarize my day", "daily", None)
    t = get_task("t1")
    assert t is not None
    assert t["title"] == "Daily report"
    assert t["schedule"] == "daily"
    assert t["active"] == 1


def test_list_tasks():
    save_task("t1", "Task 1", "prompt1", "daily", None)
    save_task("t2", "Task 2", "prompt2", "weekly", None)
    tasks = list_tasks()
    assert len(tasks) == 2


def test_toggle_task():
    save_task("t1", "Task", "prompt", "daily", None)
    toggle_task("t1", False)
    assert get_task("t1")["active"] == 0
    toggle_task("t1", True)
    assert get_task("t1")["active"] == 1


def test_delete_task():
    save_task("t1", "Task", "prompt", "daily", None)
    assert delete_task("t1") is True
    assert get_task("t1") is None
    assert delete_task("t1") is False
