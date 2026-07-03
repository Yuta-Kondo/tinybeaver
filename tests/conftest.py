from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect every test to a fresh temporary SQLite database."""
    import backend.memory as mem

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(mem, "DB_PATH", db_path)
    monkeypatch.setattr(mem, "_LEGACY_DIR", tmp_path / "no-legacy")  # skip legacy migration
    monkeypatch.setattr(mem, "_conn", None)
    yield
    conn = mem._conn
    if conn:
        conn.close()
    monkeypatch.setattr(mem, "_conn", None)
