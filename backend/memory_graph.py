"""SQLite knowledge-graph memory: core profile + entities + relations + atomic facts.

Replaces unbounded topic markdown blobs. Categories (`topics.slug`) are a fixed
catalog; facts are retrieved hybrid (FTS + Gemini embeddings) with a hard budget.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

# MECE life-domain catalog (primary filing homes). Core profile is separate —
# always-on synthesis, not a peer category. Entities cross-link across domains.
FIXED_CATEGORIES: dict[str, str] = {
    "identity": "Who Yuta is — background, values, biography (not day-to-day prefs)",
    "career": "Work, research, jobs, advisors, professional life",
    "money": "Banking, budget, taxes, investments",
    "admin": "Government, legal, and administrative paperwork",
    "home": "Housing, address, neighborhood",
    "body": "Health, fitness, sleep, medical",
    "people": "Family, friends, social relationships",
    "craft": "Skills, tools, languages, learning, engineering practice",
    "play": "Hobbies and recreation",
    "ops": "How the assistant should behave — communication & workflow prefs",
    "misc": "Explicit overflow only when nothing above fits",
}

# Legacy → MECE remaps (old topic blobs / early graph categories).
CATEGORY_ALIASES: dict[str, str] = {
    "profile": "identity",
    "phd": "career",
    "finance": "money",
    "investments": "money",
    "immigration": "admin",
    "housing": "home",
    "health": "body",
    "preferences": "ops",
    "projects": "craft",
    "ai-agent": "craft",
    "ai-tools": "craft",
    "devops-infrastructure": "craft",
    "english-learning": "craft",
    "dating": "people",
    "hair": "body",
    "clothing": "ops",
    "css-sailing": "play",
    "current": "career",
    "feedback": "ops",
}

# Resolver priority when a fact could fit multiple domains (first match wins).
RESOLVER_ORDER: tuple[str, ...] = (
    "identity",
    "admin",
    "career",
    "money",
    "home",
    "body",
    "people",
    "craft",
    "play",
    "ops",
    "misc",
)

CORE_PROFILE_MAX_CHARS = 3500
MEMORY_CONTEXT_BUDGET = 7500
FACTS_PER_CATEGORY_CAP = 80
RETRIEVE_FACT_LIMIT = 24

_ENTITY_TYPES = frozenset({"person", "org", "place", "project", "concept", "other"})


def ensure_fixed_categories() -> None:
    """Seed / refresh the closed category catalog (does not wipe custom slugs)."""
    from .memory import _get_conn

    conn = _get_conn()
    for slug, desc in FIXED_CATEGORIES.items():
        conn.execute(
            """
            INSERT INTO topics (slug, description, content)
            VALUES (?, ?, '')
            ON CONFLICT(slug) DO UPDATE SET
                description = excluded.description
            """,
            (slug, desc),
        )
    conn.commit()
    # Ensure core profile row exists.
    conn.execute(
        "INSERT OR IGNORE INTO core_profile (id, content) VALUES (1, '')"
    )
    conn.commit()
    remap_legacy_categories()


def get_core_profile() -> str:
    from .memory import _get_conn

    row = _get_conn().execute(
        "SELECT content FROM core_profile WHERE id = 1"
    ).fetchone()
    return (row["content"] if row else "") or ""


def set_core_profile(content: str) -> None:
    from .memory import _get_conn

    text = (content or "").strip()[:CORE_PROFILE_MAX_CHARS]
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO core_profile (id, content, updated_at)
        VALUES (1, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            content = excluded.content,
            updated_at = datetime('now')
        """,
        (text,),
    )
    conn.commit()


def category_summaries() -> list[dict]:
    """Categories with active fact counts for the Topics UI (fixed set first)."""
    from .memory import _get_conn

    ensure_fixed_categories()
    conn = _get_conn()
    counts = {
        r["category"]: int(r["n"])
        for r in conn.execute(
            "SELECT category, COUNT(*) AS n FROM memory_facts WHERE active = 1 GROUP BY category"
        ).fetchall()
    }
    descs = {
        r["slug"]: r["description"]
        for r in conn.execute("SELECT slug, description FROM topics").fetchall()
    }
    out = []
    seen: set[str] = set()
    for slug in RESOLVER_ORDER:
        if slug not in FIXED_CATEGORIES:
            continue
        desc = FIXED_CATEGORIES[slug]
        out.append({
            "slug": slug,
            "description": descs.get(slug) or desc,
            "fact_count": counts.get(slug, 0),
        })
        seen.add(slug)
    # Legacy categories that still have facts (should be rare after remap)
    for slug, n in sorted(counts.items()):
        if slug in seen or n <= 0:
            continue
        out.append({
            "slug": slug,
            "description": descs.get(slug) or "",
            "fact_count": n,
        })
    return out


def list_facts(
    category: str | None = None,
    *,
    active_only: bool = True,
    limit: int = 200,
) -> list[dict]:
    from .memory import _get_conn

    conn = _get_conn()
    sql = (
        "SELECT id, category, text, entity_ids, created_at, superseded_by, active "
        "FROM memory_facts WHERE 1=1"
    )
    args: list[Any] = []
    if active_only:
        sql += " AND active = 1"
    if category:
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        try:
            eids = json.loads(r["entity_ids"] or "[]")
        except json.JSONDecodeError:
            eids = []
        out.append({
            "id": r["id"],
            "category": r["category"],
            "text": r["text"],
            "entity_ids": eids,
            "created_at": r["created_at"],
            "superseded_by": r["superseded_by"],
            "active": bool(r["active"]),
        })
    return out


def get_fact(fact_id: int) -> dict | None:
    rows = list_facts(active_only=False, limit=10_000)
    for f in rows:
        if f["id"] == fact_id:
            return f
    from .memory import _get_conn
    r = _get_conn().execute(
        "SELECT id, category, text, entity_ids, created_at, superseded_by, active "
        "FROM memory_facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    if not r:
        return None
    try:
        eids = json.loads(r["entity_ids"] or "[]")
    except json.JSONDecodeError:
        eids = []
    return {
        "id": r["id"],
        "category": r["category"],
        "text": r["text"],
        "entity_ids": eids,
        "created_at": r["created_at"],
        "superseded_by": r["superseded_by"],
        "active": bool(r["active"]),
    }


def delete_fact(fact_id: int) -> bool:
    from .memory import _get_conn

    conn = _get_conn()
    cur = conn.execute(
        "UPDATE memory_facts SET active = 0 WHERE id = ?", (fact_id,)
    )
    conn.commit()
    return cur.rowcount > 0


def update_fact_text(fact_id: int, text: str) -> bool:
    from .memory import _get_conn

    text = (text or "").strip()
    if not text:
        return False
    conn = _get_conn()
    emb = None
    try:
        from .doc_embeddings import embed_bytes, embed_documents
        emb = embed_bytes(embed_documents([text])[0])
    except Exception as e:
        _log.warning("Fact re-embed failed: %s", e)
    if emb is not None:
        cur = conn.execute(
            "UPDATE memory_facts SET text = ?, embedding = ? WHERE id = ? AND active = 1",
            (text, emb, fact_id),
        )
    else:
        cur = conn.execute(
            "UPDATE memory_facts SET text = ? WHERE id = ? AND active = 1",
            (text, fact_id),
        )
    conn.commit()
    return cur.rowcount > 0


def list_entities(limit: int = 200) -> list[dict]:
    from .memory import _get_conn

    rows = _get_conn().execute(
        "SELECT id, name, type, summary, updated_at FROM entities "
        "ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def entity_neighbors(entity_id: int, limit: int = 20) -> list[dict]:
    """1-hop active relations for an entity."""
    from .memory import _get_conn

    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT r.id, r.predicate, r.valid_from, r.valid_to,
               r.from_id, r.to_id,
               ef.name AS from_name, ef.type AS from_type,
               et.name AS to_name, et.type AS to_type
        FROM relations r
        JOIN entities ef ON ef.id = r.from_id
        JOIN entities et ON et.id = r.to_id
        WHERE r.valid_to IS NULL
          AND (r.from_id = ? OR r.to_id = ?)
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (entity_id, entity_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_entity(name: str, etype: str = "concept", summary: str = "") -> int:
    from .memory import _get_conn

    name = (name or "").strip()
    if not name:
        raise ValueError("entity name required")
    etype = etype if etype in _ENTITY_TYPES else "concept"
    summary = (summary or "").strip()[:500]
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, summary FROM entities WHERE lower(name) = lower(?) AND type = ?",
        (name, etype),
    ).fetchone()
    if row:
        eid = int(row["id"])
        if summary and summary != (row["summary"] or ""):
            conn.execute(
                "UPDATE entities SET summary = ?, updated_at = datetime('now') WHERE id = ?",
                (summary, eid),
            )
            conn.commit()
        return eid
    cur = conn.execute(
        "INSERT INTO entities (name, type, summary) VALUES (?, ?, ?)",
        (name, etype, summary),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_relation(
    from_id: int,
    to_id: int,
    predicate: str,
    *,
    source_session: str = "",
) -> int:
    from .memory import _get_conn

    predicate = (predicate or "related_to").strip()[:80] or "related_to"
    conn = _get_conn()
    # Close prior identical open edge.
    conn.execute(
        """
        UPDATE relations SET valid_to = datetime('now')
        WHERE from_id = ? AND to_id = ? AND predicate = ? AND valid_to IS NULL
        """,
        (from_id, to_id, predicate),
    )
    cur = conn.execute(
        """
        INSERT INTO relations (from_id, to_id, predicate, source_session)
        VALUES (?, ?, ?, ?)
        """,
        (from_id, to_id, predicate, source_session or ""),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_fact(
    category: str,
    text: str,
    *,
    entity_ids: list[int] | None = None,
    supersedes: int | None = None,
    embedding: bytes | None = None,
) -> int:
    from .memory import _get_conn

    ensure_fixed_categories()
    category = _normalize_category(category)
    text = (text or "").strip()
    if not text:
        raise ValueError("fact text required")
    entity_ids = entity_ids or []
    conn = _get_conn()
    if embedding is None:
        try:
            from .doc_embeddings import embed_bytes, embed_documents
            embedding = embed_bytes(embed_documents([text])[0])
        except Exception as e:
            _log.warning("Fact embed skipped: %s", e)
            embedding = None
    cur = conn.execute(
        """
        INSERT INTO memory_facts (category, text, entity_ids, embedding, active)
        VALUES (?, ?, ?, ?, 1)
        """,
        (category, text, json.dumps(entity_ids), embedding),
    )
    new_id = int(cur.lastrowid)
    if supersedes:
        conn.execute(
            "UPDATE memory_facts SET active = 0, superseded_by = ? WHERE id = ?",
            (new_id, supersedes),
        )
    conn.commit()
    _enforce_category_cap(category)
    return new_id


def _normalize_category(category: str) -> str:
    """Map any slug/alias onto the MECE catalog (unknown → misc)."""
    from .memory import _get_conn

    c = (category or "").strip().lower().replace(" ", "-")
    if not c:
        return "misc"
    if c in FIXED_CATEGORIES:
        return c
    if c in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[c]
    # Legacy topic that still exists but isn't aliased → misc (not invent new domains).
    row = _get_conn().execute(
        "SELECT slug FROM topics WHERE slug = ?", (c,)
    ).fetchone()
    if row and c not in FIXED_CATEGORIES:
        return "misc"
    return "misc"


def remap_legacy_categories() -> int:
    """Rewrite memory_facts.category from legacy slugs to MECE domains."""
    from .memory import _get_conn

    conn = _get_conn()
    n = 0
    for old, new in CATEGORY_ALIASES.items():
        if old == new or new not in FIXED_CATEGORIES:
            continue
        # Ensure destination topic exists (FK).
        conn.execute(
            "INSERT OR IGNORE INTO topics (slug, description, content) VALUES (?, ?, '')",
            (new, FIXED_CATEGORIES.get(new, "")),
        )
        cur = conn.execute(
            "UPDATE memory_facts SET category = ? WHERE category = ?",
            (new, old),
        )
        n += cur.rowcount or 0
    # Any active fact still outside the catalog → misc.
    placeholders = ",".join("?" * len(FIXED_CATEGORIES))
    cur = conn.execute(
        f"UPDATE memory_facts SET category = 'misc' "
        f"WHERE category NOT IN ({placeholders})",
        tuple(FIXED_CATEGORIES.keys()),
    )
    n += cur.rowcount or 0
    conn.commit()
    if n:
        _log.info("Remapped %d memory fact categories to MECE domains", n)
    return n


def _enforce_category_cap(category: str) -> None:
    from .memory import _get_conn

    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id FROM memory_facts
        WHERE category = ? AND active = 1
        ORDER BY created_at DESC
        """,
        (category,),
    ).fetchall()
    if len(rows) <= FACTS_PER_CATEGORY_CAP:
        return
    drop = [int(r["id"]) for r in rows[FACTS_PER_CATEGORY_CAP:]]
    conn.executemany(
        "UPDATE memory_facts SET active = 0 WHERE id = ?",
        [(i,) for i in drop],
    )
    conn.commit()


def supersede_similar_facts(category: str, new_text: str, *, threshold: float = 0.88) -> list[int]:
    """Deactivate near-duplicate active facts in a category (cosine on embeddings)."""
    from .memory import _get_conn
    from .doc_embeddings import cosine, decode_bytes, embed_documents

    try:
        qvec = embed_documents([new_text])[0]
    except Exception:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, embedding FROM memory_facts WHERE category = ? AND active = 1 AND embedding IS NOT NULL",
        (category,),
    ).fetchall()
    doomed: list[int] = []
    for r in rows:
        try:
            sim = cosine(qvec, decode_bytes(r["embedding"]))
        except Exception:
            continue
        if sim >= threshold:
            doomed.append(int(r["id"]))
    for fid in doomed:
        conn.execute(
            "UPDATE memory_facts SET active = 0 WHERE id = ?", (fid,)
        )
    if doomed:
        conn.commit()
    return doomed


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_memory(query: str, *, categories: list[str] | None = None) -> str:
    """Build the Memory system block: core profile + top facts + graph neighbors."""
    ensure_fixed_categories()
    parts: list[str] = []
    budget = MEMORY_CONTEXT_BUDGET

    core = get_core_profile().strip()
    if core:
        take = core[: min(CORE_PROFILE_MAX_CHARS, budget)]
        parts.append(f"### Core profile\n{take}")
        budget -= len(take)

    if budget <= 500:
        return "\n\n".join(parts)

    facts = _search_facts(query, categories=categories, limit=RETRIEVE_FACT_LIMIT)
    entity_ids: set[int] = set()
    fact_lines: list[str] = []
    for f in facts:
        line = f"- [{f['category']}] {f['text']}"
        if budget - len(line) < 200:
            break
        fact_lines.append(line)
        budget -= len(line) + 1
        for eid in f.get("entity_ids") or []:
            try:
                entity_ids.add(int(eid))
            except (TypeError, ValueError):
                pass

    if fact_lines:
        parts.append("### Relevant facts\n" + "\n".join(fact_lines))

    # Also search entities by name substring / embedding-ish FTS on name.
    for eid in list(_match_entities(query))[:8]:
        entity_ids.add(eid)

    graph_lines: list[str] = []
    for eid in list(entity_ids)[:12]:
        if budget < 300:
            break
        for rel in entity_neighbors(eid, limit=6):
            line = (
                f"- {rel['from_name']} —{rel['predicate']}→ {rel['to_name']}"
            )
            if line in graph_lines:
                continue
            if budget - len(line) < 150:
                break
            graph_lines.append(line)
            budget -= len(line) + 1

    if graph_lines:
        parts.append("### Related entities\n" + "\n".join(graph_lines[:20]))

    return "\n\n".join(parts)


def _match_entities(query: str) -> list[int]:
    from .memory import _get_conn

    q = (query or "").strip()
    if not q:
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", q)
    if not tokens:
        return []
    conn = _get_conn()
    ids: list[int] = []
    seen: set[int] = set()
    for tok in tokens[:12]:
        rows = conn.execute(
            "SELECT id FROM entities WHERE name LIKE ? LIMIT 5",
            (f"%{tok}%",),
        ).fetchall()
        for r in rows:
            i = int(r["id"])
            if i not in seen:
                seen.add(i)
                ids.append(i)
    return ids


def _search_facts(
    query: str,
    *,
    categories: list[str] | None = None,
    limit: int = 24,
) -> list[dict]:
    """Hybrid fact retrieval with RRF across FTS + semantic."""
    from .memory import _get_conn

    conn = _get_conn()
    cat_filter = ""
    cat_args: list[Any] = []
    if categories:
        cats = [_normalize_category(c) for c in categories]
        placeholders = ",".join("?" * len(cats))
        cat_filter = f" AND f.category IN ({placeholders})"
        cat_args = cats

    ranked: dict[int, float] = {}
    items: dict[int, dict] = {}

    def _rrf(cid: int, rank: int, weight: float = 1.0) -> None:
        ranked[cid] = ranked.get(cid, 0.0) + weight / (60 + rank)

    # FTS
    fts_q = _fact_fts_query(query)
    if fts_q:
        try:
            rows = conn.execute(
                f"""
                SELECT f.id, f.category, f.text, f.entity_ids,
                       bm25(memory_facts_fts) AS rank
                FROM memory_facts_fts
                JOIN memory_facts f ON f.id = memory_facts_fts.rowid
                WHERE f.active = 1
                  AND memory_facts_fts MATCH ?
                  {cat_filter}
                ORDER BY rank
                LIMIT ?
                """,
                (fts_q, *cat_args, limit * 2),
            ).fetchall()
            for i, r in enumerate(rows):
                fid = int(r["id"])
                items[fid] = _fact_row(r)
                _rrf(fid, i, weight=1.0)
        except Exception:
            pass

    # Semantic
    try:
        from .doc_embeddings import cosine, decode_bytes, embed_query

        qvec = embed_query(query)
        rows = conn.execute(
            f"""
            SELECT f.id, f.category, f.text, f.entity_ids, f.embedding
            FROM memory_facts f
            WHERE f.active = 1 AND f.embedding IS NOT NULL
            {cat_filter}
            """,
            tuple(cat_args),
        ).fetchall()
        sims: list[tuple[float, Any]] = []
        for r in rows:
            try:
                sim = cosine(qvec, decode_bytes(r["embedding"]))
            except Exception:
                continue
            if sim > 0.28:
                sims.append((sim, r))
        sims.sort(key=lambda x: x[0], reverse=True)
        for i, (_, r) in enumerate(sims[: limit * 2]):
            fid = int(r["id"])
            items[fid] = _fact_row(r)
            _rrf(fid, i, weight=1.2)
    except Exception as e:
        _log.debug("Semantic fact search skipped: %s", e)

    # Category bias: if classifier passed categories, boost those already listed.
    ordered = sorted(ranked.keys(), key=lambda k: ranked[k], reverse=True)[:limit]
    return [items[i] for i in ordered if i in items]


def _fact_row(r) -> dict:
    try:
        eids = json.loads(r["entity_ids"] or "[]")
    except (json.JSONDecodeError, TypeError, KeyError):
        eids = []
    return {
        "id": int(r["id"]),
        "category": r["category"],
        "text": r["text"] or "",
        "entity_ids": eids,
    }


def _fact_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", query or "")
    stop = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "what",
        "when", "where", "which", "with", "from", "this", "that", "have", "about",
        "please", "tell", "does", "my", "me", "your",
    }
    keep = [t for t in tokens if t.lower() not in stop][:20]
    if not keep:
        keep = tokens[:8]
    return " OR ".join(f'"{t}"' for t in keep)


# ---------------------------------------------------------------------------
# Write path (LLM extract → graph)
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
You extract durable personal memory about Yuta from a conversation into a knowledge graph.

Allowed categories (MECE life domains — pick exactly one primary home per fact):
{categories}

Filing resolver (first match wins if ambiguous):
identity → admin → career → money → home → body → people → craft → play → ops → misc.
Use misc only when nothing else fits. Do not invent categories.
ops = how the assistant should behave; identity = who Yuta is.
career includes work/research; admin includes legal/government paperwork.

Existing entities (reuse names when the same person/org/place/project):
{entities}

Current memory (for conflict detection only — do not repeat unchanged facts):
{current}

Conversation:
User: {user}
Assistant: {assistant}

Return ONLY JSON:
{{
  "facts": [
    {{
      "category": "career",
      "text": "atomic personal fact about Yuta",
      "entities": [{{"name": "Entity", "type": "person|org|place|project|concept|other", "summary": "optional"}}],
      "supersedes_hint": "optional substring of an old fact this replaces, or null"
    }}
  ],
  "relations": [
    {{"from": "EntityA", "to": "EntityB", "predicate": "advised_by|works_at|lives_in|related_to|..."}}
  ],
  "core_profile_patch": "optional short replacement for the always-on profile if identity/prefs changed, else null"
}}

Rules:
- Only personal facts about Yuta (prefs, decisions, plans, status, people in his life).
- Atomic: one fact per item. No essays. No general knowledge.
- If nothing new, return {{"facts":[], "relations":[], "core_profile_patch": null}}.
"""


def update_memory_graph(
    categories: list[str],
    user_msg: str,
    assistant_msg: str,
    *,
    session_id: str = "",
) -> tuple[list[str], float]:
    """Extract facts/entities from a turn and write them. Returns (touched_categories, cost)."""
    from .llm import llm_json, strip_code_fence
    from .models import UTILITY_MODEL

    ensure_fixed_categories()
    cats = [_normalize_category(c) for c in (categories or list(FIXED_CATEGORIES))]
    cats = list(dict.fromkeys(cats))  # unique, preserve order

    existing_ents = list_entities(limit=80)
    ent_lines = "\n".join(
        f"- {e['name']} ({e['type']}): {e.get('summary') or ''}" for e in existing_ents
    ) or "(none yet)"

    current_bits = []
    for c in cats[:6]:
        for f in list_facts(c, limit=12):
            current_bits.append(f"[{c}] {f['text']}")
    current = "\n".join(current_bits[:40]) or "(empty)"

    prompt = _EXTRACT_PROMPT.format(
        categories=", ".join(FIXED_CATEGORIES.keys()),
        entities=ent_lines,
        current=current,
        user=user_msg[:3000],
        assistant=assistant_msg[:1500],
    )
    text, cost = llm_json(prompt, model=UTILITY_MODEL, max_tokens=2500)
    try:
        data = json.loads(strip_code_fence(text))
    except json.JSONDecodeError:
        _log.warning("Memory extract JSON parse failed")
        return [], cost

    touched: set[str] = set()
    name_to_id: dict[str, int] = {
        e["name"].lower(): int(e["id"]) for e in existing_ents
    }

    for fact in data.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        ftext = (fact.get("text") or "").strip()
        if not ftext:
            continue
        cat = _normalize_category(fact.get("category") or "projects")
        eids: list[int] = []
        for ent in fact.get("entities") or []:
            if not isinstance(ent, dict):
                continue
            ename = (ent.get("name") or "").strip()
            if not ename:
                continue
            etype = ent.get("type") or "concept"
            eid = upsert_entity(ename, etype, ent.get("summary") or "")
            name_to_id[ename.lower()] = eid
            eids.append(eid)
        supersedes = None
        hint = (fact.get("supersedes_hint") or "").strip()
        if hint:
            for old in list_facts(cat, limit=40):
                if hint.lower() in old["text"].lower():
                    supersedes = old["id"]
                    break
        # Near-dup cleanup before insert when no explicit supersede.
        if not supersedes:
            supersede_similar_facts(cat, ftext)
        add_fact(cat, ftext, entity_ids=eids, supersedes=supersedes)
        touched.add(cat)

    for rel in data.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        a = (rel.get("from") or "").strip()
        b = (rel.get("to") or "").strip()
        pred = (rel.get("predicate") or "related_to").strip()
        if not a or not b:
            continue
        fa = name_to_id.get(a.lower()) or upsert_entity(a)
        tb = name_to_id.get(b.lower()) or upsert_entity(b)
        name_to_id[a.lower()] = fa
        name_to_id[b.lower()] = tb
        add_relation(fa, tb, pred, source_session=session_id)

    patch = data.get("core_profile_patch")
    if isinstance(patch, str) and patch.strip():
        set_core_profile(patch.strip())
        touched.add("profile")

    return sorted(touched), cost


def save_explicit_fact(category: str, text: str) -> str:
    """Handle [[SAVE:category:fact]] markers."""
    cat = _normalize_category(category)
    text = (text or "").strip()
    if not text:
        return cat
    supersede_similar_facts(cat, text)
    add_fact(cat, text)
    return cat


def consolidate_graph() -> dict:
    """Reflect: merge near-duplicate facts and trim empty entity summaries via LLM."""
    from .llm import llm_json, strip_code_fence
    from .models import UTILITY_MODEL

    facts = list_facts(limit=120)
    if not facts:
        return {"updated": [], "merged": 0}

    listing = "\n".join(f"{f['id']}|{f['category']}|{f['text']}" for f in facts)
    prompt = f"""You clean a personal knowledge-graph fact list for Yuta.

Facts (id|category|text):
{listing}

Return ONLY JSON:
{{
  "deactivate": [ids that are redundant or obsolete],
  "core_profile": "optional refreshed short core profile, or null"
}}
Deactivate near-duplicates and outdated status. Keep the newest accurate fact.
If nothing to change: {{"deactivate": [], "core_profile": null}}"""
    text, cost = llm_json(prompt, model=UTILITY_MODEL, max_tokens=1500)
    try:
        data = json.loads(strip_code_fence(text))
    except json.JSONDecodeError:
        return {"updated": [], "merged": 0, "cost_usd": cost}

    n = 0
    for fid in data.get("deactivate") or []:
        try:
            if delete_fact(int(fid)):
                n += 1
        except (TypeError, ValueError):
            pass
    core = data.get("core_profile")
    updated = []
    if isinstance(core, str) and core.strip():
        set_core_profile(core.strip())
        updated.append("profile")
    return {"updated": updated, "merged": n, "cost_usd": cost}


# ---------------------------------------------------------------------------
# One-shot migration from topic content blobs
# ---------------------------------------------------------------------------

def needs_topic_blob_migration() -> bool:
    from .memory import _get_conn

    row = _get_conn().execute(
        "SELECT COUNT(*) AS n FROM topics WHERE length(trim(content)) > 40"
    ).fetchone()
    return int(row["n"] or 0) > 0


def migrate_topic_blobs_to_graph() -> dict:
    """Parse legacy topic markdown into facts/entities; clear topic content."""
    from .llm import llm_json, strip_code_fence
    from .memory import _get_conn
    from .models import UTILITY_MODEL

    ensure_fixed_categories()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT slug, description, content FROM topics WHERE length(trim(content)) > 20"
    ).fetchall()
    if not rows:
        return {"migrated": 0, "facts": 0}

    total_facts = 0
    migrated = 0
    cost_sum = 0.0
    profile_bits: list[str] = []

    for r in rows:
        slug = r["slug"]
        content = (r["content"] or "").strip()
        if not content:
            continue
        cat = _normalize_category(slug if slug in FIXED_CATEGORIES else "misc")
        prompt = f"""Convert this personal memory note about Yuta into atomic facts for category "{cat}".

Note:
{content[:12000]}

Return ONLY JSON:
{{
  "facts": [{{"text": "...", "entities": [{{"name": "...", "type": "person|org|place|project|concept|other"}}]}}],
  "relations": [{{"from": "...", "to": "...", "predicate": "..."}}],
  "core_snippets": ["short identity lines if this note has profile info"]
}}
Atomic personal facts only. No essays."""
        try:
            text, cost = llm_json(prompt, model=UTILITY_MODEL, max_tokens=3500)
            cost_sum += cost
            data = json.loads(strip_code_fence(text))
        except Exception as e:
            _log.warning("Migrate %s failed: %s", slug, e)
            continue

        name_to_id: dict[str, int] = {}
        for fact in data.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            ftext = (fact.get("text") or "").strip()
            if not ftext:
                continue
            eids = []
            for ent in fact.get("entities") or []:
                if not isinstance(ent, dict):
                    continue
                ename = (ent.get("name") or "").strip()
                if not ename:
                    continue
                eid = upsert_entity(ename, ent.get("type") or "concept")
                name_to_id[ename.lower()] = eid
                eids.append(eid)
            add_fact(cat, ftext, entity_ids=eids)
            total_facts += 1

        for rel in data.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            a = (rel.get("from") or "").strip()
            b = (rel.get("to") or "").strip()
            if not a or not b:
                continue
            fa = name_to_id.get(a.lower()) or upsert_entity(a)
            tb = name_to_id.get(b.lower()) or upsert_entity(b)
            add_relation(fa, tb, rel.get("predicate") or "related_to")

        for snip in data.get("core_snippets") or []:
            if isinstance(snip, str) and snip.strip():
                profile_bits.append(snip.strip())

        conn.execute(
            "UPDATE topics SET content = '', updated_at = datetime('now') WHERE slug = ?",
            (slug,),
        )
        conn.commit()
        migrated += 1

    if profile_bits and not get_core_profile().strip():
        set_core_profile("\n".join(f"- {s}" for s in profile_bits[:40]))

    return {
        "migrated": migrated,
        "facts": total_facts,
        "cost_usd": round(cost_sum, 4),
    }
