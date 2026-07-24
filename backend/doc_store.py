"""Durable on-disk storage for uploaded session documents.

Original files live under data/documents/{session_id}/{doc_id}_{safe_name}
so large PDFs survive across turns (ChatGPT/Claude style) without staying in RAM.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from .memory import DB_PATH

_log = logging.getLogger(__name__)

DOCS_DIR = DB_PATH.parent / "documents"

_ingest_lock = threading.Lock()
_active_ingests: set[int] = set()


def _safe_name(name: str) -> str:
    base = Path(name or "file").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    return cleaned[:160]


def path_for(session_id: str, doc_id: int, name: str) -> Path:
    return DOCS_DIR / session_id / f"{doc_id}_{_safe_name(name)}"


def save_bytes(session_id: str, doc_id: int, name: str, data: bytes) -> str:
    """Write original bytes to disk. Returns relative path string for the DB."""
    path = path_for(session_id, doc_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # Store path relative to data/ so the volume mount stays portable.
    return str(path.relative_to(DB_PATH.parent))


def resolve_path(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    p = Path(storage_path)
    if not p.is_absolute():
        p = DB_PATH.parent / p
    return p if p.exists() else None


def delete_file(storage_path: str | None) -> None:
    p = resolve_path(storage_path)
    if not p:
        return
    try:
        p.unlink(missing_ok=True)
        # Remove empty session dir.
        parent = p.parent
        if parent.exists() and parent != DOCS_DIR and not any(parent.iterdir()):
            parent.rmdir()
    except OSError as e:
        _log.warning("Could not delete document file %s: %s", p, e)


def start_ingest(doc_id: int) -> None:
    """Run extract → chunk → FTS in a daemon thread (one at a time per doc)."""
    with _ingest_lock:
        if doc_id in _active_ingests:
            return
        _active_ingests.add(doc_id)

    def _run() -> None:
        try:
            _ingest_document(doc_id)
        finally:
            with _ingest_lock:
                _active_ingests.discard(doc_id)

    threading.Thread(target=_run, name=f"doc-ingest-{doc_id}", daemon=True).start()


def _ingest_document(doc_id: int) -> None:
    from .file_extract import chunk_text, extract_file_bytes
    from .memory import (
        add_document_chunks,
        clear_document_chunks,
        get_session_document,
        update_session_document,
    )

    row = get_session_document(doc_id)
    if not row:
        return

    update_session_document(doc_id, status="processing", error="")
    path = resolve_path(row.get("storage_path"))
    if not path:
        update_session_document(doc_id, status="failed", error="Original file missing on disk")
        return

    try:
        data = path.read_bytes()
        text, cost = extract_file_bytes(data, row["name"])
        if not (text or "").strip():
            update_session_document(
                doc_id, status="failed", error="No content extracted from file", cost_usd=cost
            )
            return

        clear_document_chunks(doc_id)
        chunks = chunk_text(text)
        if chunks:
            add_document_chunks(row["session_id"], doc_id, chunks)

        update_session_document(
            doc_id,
            status="ready",
            text=text,
            chars=len(text),
            cost_usd=cost,
            error="",
        )
        _log.info(
            "Ingested doc %s (%s): %d chars, %d chunks, $%.4f",
            doc_id, row["name"], len(text), len(chunks), cost,
        )
    except Exception as e:
        _log.exception("Ingest failed for doc %s", doc_id)
        update_session_document(doc_id, status="failed", error=str(e)[:500])
