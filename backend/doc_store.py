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
_cancel_flags: dict[int, threading.Event] = {}


class IngestCancelled(Exception):
    """Raised when the user stops an in-flight document ingest."""


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


def cancel_ingest(doc_id: int) -> None:
    """Signal a running ingest to stop (also used when the doc is deleted)."""
    with _ingest_lock:
        ev = _cancel_flags.get(doc_id)
    if ev:
        ev.set()


def is_cancelled(doc_id: int) -> bool:
    with _ingest_lock:
        ev = _cancel_flags.get(doc_id)
    return bool(ev and ev.is_set())


def reset_stuck_ingests() -> int:
    """On startup: any 'processing' row has no live worker after a restart."""
    from .memory import _get_conn, update_session_document

    rows = _get_conn().execute(
        "SELECT id FROM session_documents WHERE status IN ('processing', 'pending')"
    ).fetchall()
    for r in rows:
        update_session_document(
            r["id"],
            status="failed",
            error="Stopped — server restarted during indexing. Remove and re-upload.",
        )
    return len(rows)


def start_ingest(doc_id: int) -> None:
    """Run extract → chunk → embed → FTS in a daemon thread."""
    with _ingest_lock:
        if doc_id in _active_ingests:
            return
        _active_ingests.add(doc_id)
        _cancel_flags[doc_id] = threading.Event()

    def _run() -> None:
        try:
            _ingest_document(doc_id)
        finally:
            with _ingest_lock:
                _active_ingests.discard(doc_id)
                _cancel_flags.pop(doc_id, None)

    threading.Thread(target=_run, name=f"doc-ingest-{doc_id}", daemon=True).start()


def start_reindex(doc_id: int) -> None:
    """Re-chunk + re-embed an already-extracted document (no re-OCR)."""
    with _ingest_lock:
        if doc_id in _active_ingests:
            return
        _active_ingests.add(doc_id)
        _cancel_flags[doc_id] = threading.Event()

    def _run() -> None:
        try:
            _reindex_document(doc_id)
        finally:
            with _ingest_lock:
                _active_ingests.discard(doc_id)
                _cancel_flags.pop(doc_id, None)

    threading.Thread(target=_run, name=f"doc-reindex-{doc_id}", daemon=True).start()


def kick_missing_embeddings(session_id: str) -> int:
    """Start background reindex for ready docs that lack Gemini embeddings."""
    from .memory import _get_conn

    rows = _get_conn().execute(
        """
        SELECT d.id
        FROM   session_documents d
        WHERE  d.session_id = ?
          AND  d.status = 'ready'
          AND  length(COALESCE(d.text, '')) > 0
          AND  (
            NOT EXISTS (
              SELECT 1 FROM session_document_chunks c WHERE c.doc_id = d.id
            )
            OR EXISTS (
              SELECT 1 FROM session_document_chunks c
              WHERE c.doc_id = d.id AND c.embedding IS NULL
            )
          )
        """,
        (session_id,),
    ).fetchall()
    n = 0
    for r in rows:
        start_reindex(int(r["id"]))
        n += 1
    return n


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

    update_session_document(doc_id, status="processing", error="Starting extract…")
    path = resolve_path(row.get("storage_path"))
    if not path:
        update_session_document(doc_id, status="failed", error="Original file missing on disk")
        return

    def on_progress(_done: int, _total: int, msg: str) -> None:
        if is_cancelled(doc_id):
            raise IngestCancelled()
        try:
            update_session_document(doc_id, error=msg[:200])
        except Exception:
            pass

    def check_cancel() -> None:
        if is_cancelled(doc_id):
            raise IngestCancelled()

    try:
        check_cancel()
        data = path.read_bytes()
        text, cost = extract_file_bytes(
            data, row["name"], on_progress=on_progress, should_cancel=lambda: is_cancelled(doc_id)
        )
        check_cancel()
        if not (text or "").strip():
            update_session_document(
                doc_id, status="failed", error="No content extracted from file", cost_usd=cost
            )
            return

        update_session_document(doc_id, text=text, chars=len(text), cost_usd=cost)
        _chunk_and_embed(doc_id, row["session_id"], text, cost)
    except IngestCancelled:
        _log.info("Ingest cancelled for doc %s", doc_id)
        if get_session_document(doc_id):
            update_session_document(doc_id, status="failed", error="Stopped by user")
    except Exception as e:
        _log.exception("Ingest failed for doc %s", doc_id)
        if get_session_document(doc_id):
            update_session_document(doc_id, status="failed", error=str(e)[:500])


def _reindex_document(doc_id: int) -> None:
    from .memory import get_session_document, update_session_document

    row = get_session_document(doc_id)
    if not row:
        return
    text = (row.get("text") or "").strip()
    if not text:
        update_session_document(
            doc_id,
            status="failed",
            error="No extracted text to reindex — re-upload the file",
        )
        return

    try:
        update_session_document(doc_id, status="processing", error="Reindexing…")
        cost = float(row.get("cost_usd") or 0)
        _chunk_and_embed(doc_id, row["session_id"], text, cost)
    except IngestCancelled:
        _log.info("Reindex cancelled for doc %s", doc_id)
        if get_session_document(doc_id):
            update_session_document(doc_id, status="failed", error="Stopped by user")
    except Exception as e:
        _log.exception("Reindex failed for doc %s", doc_id)
        if get_session_document(doc_id):
            update_session_document(doc_id, status="failed", error=str(e)[:500])


def _chunk_and_embed(doc_id: int, session_id: str, text: str, cost: float) -> None:
    from .doc_embeddings import EmbedCancelled, embed_bytes, embed_documents
    from .file_extract import chunk_text
    from .memory import (
        add_document_chunks,
        clear_document_chunks,
        update_session_document,
    )

    def check_cancel() -> None:
        if is_cancelled(doc_id):
            raise IngestCancelled()

    update_session_document(doc_id, error="Chunking for search…")
    clear_document_chunks(doc_id)
    chunks = chunk_text(text)
    check_cancel()

    if chunks:
        update_session_document(
            doc_id, error=f"Embedding… 0/{len(chunks)}"
        )

        def on_embed(done: int, total: int) -> None:
            check_cancel()
            try:
                update_session_document(
                    doc_id, error=f"Embedding… {done}/{total}"
                )
            except Exception:
                pass

        try:
            vectors = embed_documents(
                [c["text"] for c in chunks],
                on_progress=on_embed,
                should_cancel=lambda: is_cancelled(doc_id),
            )
            for c, vec in zip(chunks, vectors):
                c["embedding"] = embed_bytes(vec)
        except EmbedCancelled:
            raise IngestCancelled()
        except Exception as e:
            # Still index FTS without vectors — lexical search still works.
            _log.warning("Embedding failed for doc %s (%s); storing FTS-only chunks", doc_id, e)
            update_session_document(doc_id, error=f"Embedding skipped: {e}"[:200])

        check_cancel()
        add_document_chunks(session_id, doc_id, chunks)

    update_session_document(
        doc_id,
        status="ready",
        text=text,
        chars=len(text),
        cost_usd=cost,
        error="",
    )
    _log.info(
        "Indexed doc %s: %d chars, %d chunks, $%.4f",
        doc_id, len(text), len(chunks), cost,
    )
