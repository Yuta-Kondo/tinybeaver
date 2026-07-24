"""Remote Gemini embeddings for session-document chunks.

Uses the Google GenAI API so we never load ONNX/fastembed into the VPS
(local embeddings OOM'd ~3.7GB boxes during textbook ingest).
"""
from __future__ import annotations

import logging
import os
import struct
import time
from typing import Callable

_log = logging.getLogger(__name__)

# Compact vectors keep SQLite BLOBs and cosine search cheap on the VPS.
_MODEL = "text-embedding-004"
_DIM = 256
_BATCH = 48  # stay well under API batch limits
_MAX_CHARS = 6_000  # ~2k tokens; API truncates anyway


class EmbedCancelled(Exception):
    """Raised when the caller cancels mid-batch embedding."""


def embed_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def decode_bytes(b: bytes) -> list[float]:
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _client():
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set — cannot embed documents")
    from google import genai as google_genai
    return google_genai.Client(api_key=api_key)


def _embed_batch(texts: list[str], *, task_type: str) -> list[list[float]]:
    from google.genai import types as gtypes

    client = _client()
    cleaned = [(t or "")[:_MAX_CHARS] or " " for t in texts]
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            result = client.models.embed_content(
                model=_MODEL,
                contents=cleaned,
                config=gtypes.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=_DIM,
                ),
            )
            embeddings = getattr(result, "embeddings", None) or []
            out: list[list[float]] = []
            for emb in embeddings:
                vals = list(getattr(emb, "values", None) or [])
                out.append(vals)
            if len(out) != len(cleaned):
                raise RuntimeError(
                    f"embed_content returned {len(out)} vectors for {len(cleaned)} texts"
                )
            return out
        except Exception as e:
            last_err = e
            _log.warning("Gemini embed attempt %d failed: %s", attempt + 1, e)
            time.sleep(0.8 * (attempt + 1))
    raise last_err or RuntimeError("Gemini embed failed")


def embed_query(text: str) -> list[float]:
    """Embed a user question for retrieval."""
    return _embed_batch([text], task_type="RETRIEVAL_QUERY")[0]


def embed_documents(
    texts: list[str],
    *,
    on_progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[list[float]]:
    """Batch-embed document passages. Returns one vector per input text."""
    if not texts:
        return []
    out: list[list[float]] = []
    total = len(texts)
    for i in range(0, total, _BATCH):
        if should_cancel and should_cancel():
            raise EmbedCancelled()
        batch = texts[i : i + _BATCH]
        out.extend(_embed_batch(batch, task_type="RETRIEVAL_DOCUMENT"))
        if on_progress:
            on_progress(min(i + len(batch), total), total)
        if i + _BATCH < total:
            time.sleep(0.05)
    return out
