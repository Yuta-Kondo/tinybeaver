"""Semantic search via fastembed (ONNX, no PyTorch required).
Model downloads ~50MB on first use to ~/.cache/fastembed/.
"""
from __future__ import annotations

import struct
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_model: "TextEmbedding | None" = None
_model_lock = threading.Lock()
_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def _get_model() -> "TextEmbedding":
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import TextEmbedding
                _model = TextEmbedding(model_name=_MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    model = _get_model()
    vecs = list(model.embed([text]))
    return vecs[0].tolist()


def embed_many(texts: list[str]) -> list[list[float]]:
    """Batch-embed texts (much faster than one-by-one for document chunking)."""
    if not texts:
        return []
    model = _get_model()
    return [v.tolist() for v in model.embed(texts)]


def embed_bytes(text: str) -> bytes:
    vec = embed(text)
    return struct.pack(f"{len(vec)}f", *vec)


def vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def decode_bytes(b: bytes) -> list[float]:
    n = len(b) // 4
    return list(struct.unpack(f"{n}f", b))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_search(query: str, limit: int = 8) -> list[dict]:
    """Return topics sorted by semantic similarity to query."""
    from .memory import get_all_topic_embeddings, save_topic_embedding

    query_vec = embed(query)
    rows = get_all_topic_embeddings()

    scored: list[tuple[float, dict]] = []
    for row in rows:
        emb_bytes = row.get("embedding")
        if emb_bytes:
            topic_vec = decode_bytes(emb_bytes)
        else:
            # Compute and cache on first access
            text = f"{row['slug']} {row['description']} {row['content']}"
            topic_vec = embed(text)
            save_topic_embedding(row["slug"], embed_bytes(text))

        score = cosine(query_vec, topic_vec)
        scored.append((score, {"slug": row["slug"], "score": round(score, 3)}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit] if item["score"] > 0.2]


def reindex_all() -> int:
    """Recompute embeddings for all topics. Returns count updated."""
    from .memory import get_all_topic_embeddings, save_topic_embedding

    rows = get_all_topic_embeddings()
    count = 0
    for row in rows:
        text = f"{row['slug']} {row['description']} {row['content']}"
        save_topic_embedding(row["slug"], embed_bytes(text))
        count += 1
    return count
