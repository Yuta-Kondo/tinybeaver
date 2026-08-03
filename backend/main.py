from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePath

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import gmail as gmail_module
from .classifier import classify
from .llm import anthropic_client, finalize_stream, llm_json, sse, strip_code_fence
from .memory import (
    add_session_document,
    available_topics,
    create_topic,
    delete_message,
    delete_session_db,
    delete_session_document,
    delete_task,
    edit_message,
    get_api_messages,
    get_session,
    get_session_documents,
    get_task,
    list_sessions,
    list_tasks,
    save_message,
    save_session,
    save_task,
    search_document_chunks,
    search_sessions,
    toggle_task,
    update_message_meta,
    update_session_summary,
    update_session_title,
    update_task_next_run,
)
from .models import (
    ALLOWED_MODELS,
    DEFAULT_MODEL,
    MODELS,
    MOA_AGENTS,
    MOA_CONFIDENCE_FOOTER,
    MOA_GLM_API_MODEL,
    MOA_SYNTHESIS_MODEL,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_GLM,
    UTILITY_MODEL,
    calc_cost,
    ChatRequest,
    SessionInfo,
)
from .providers import (
    convert_gemini_messages,
    flatten_system,
    stream_gemini,
    stream_glm,
)


# ---------------------------------------------------------------------------
# Lifespan: init DB + scheduler on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: touch DB to run migrations + seed fixed categories
    available_topics()
    try:
        from .memory_graph import ensure_fixed_categories, needs_topic_blob_migration, migrate_topic_blobs_to_graph
        ensure_fixed_categories()
        if needs_topic_blob_migration():
            import threading
            def _migrate():
                try:
                    result = migrate_topic_blobs_to_graph()
                    print(f"Memory graph migration: {result}")
                except Exception as e:
                    print(f"Memory graph migration failed: {e}")
            threading.Thread(target=_migrate, name="memory-migrate", daemon=True).start()
            print("Started background migration of topic blobs → knowledge graph")
    except Exception as e:
        print(f"Memory graph startup warning: {e}")
    # Clear orphaned "processing" docs left by a previous crash/restart.
    try:
        from .doc_store import reset_stuck_ingests
        n = reset_stuck_ingests()
        if n:
            print(f"Reset {n} stuck document ingest(s)")
    except Exception as e:
        print(f"Document ingest reset warning: {e}")
    # Start task scheduler
    try:
        from .scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler startup warning: {e}")
    yield
    # Shutdown: scheduler cleanup happens automatically


app = FastAPI(title="Personal AI Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared Anthropic client + cost calculation live in backend.llm / backend.models.
# Contact email used in outbound request headers and push VAPID claims.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "contact@example.com")

# Thin alias so the existing generator code reads naturally.
_client = anthropic_client()
_calc_cost = calc_cost


_STATIC_SYSTEM = """\
You are Yuta's personal AI assistant with access to structured memory about \
his life, work, and goals — PhD program, finances, immigration, housing search, \
and ongoing projects. Speak directly and concisely.

Format responses in Markdown. Use LaTeX for all mathematics \
(inline: $...$, block: $$...$$).

To explicitly save a fact to memory mid-response, write:
[[SAVE:category:The fact to save.]]
Categories (MECE): identity, career, money, admin, home, body, people, craft, play, ops, misc.
Use sparingly — only for personal facts about Yuta (preferences, decisions, plans, experiences). \
Never save general knowledge, definitions, or facts that could be looked up online.

When you mention a specific place the user would want to visit (a store, restaurant, \
venue, address), add a map marker on its own line:
[[MAP:Place Name, City]]
Only use this for concrete, visitable places — not general areas or hypothetical addresses.

"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MENTION_RE = re.compile(r'@([\w-]+)')
_SAVE_RE = re.compile(r'\[\[SAVE:([\w-]+):([^\]]+)\]\]')
_MAP_RE = re.compile(r'\[\[MAP:([^\]]+)\]\]')
_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
_ADDRESS_RE = re.compile(
    r'\b\d{1,5}\s+(?:[A-Za-z]+\.?\s+){1,4}'
    r'(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|'
    r'Way|Place|Pl|Court|Ct|Circle|Cir|Highway|Hwy|Parkway|Pkwy|'
    r'Terrace|Terr?|Crescent|Cres|Trail|Tr|Gate|Path|Row|Walk|Close|Cl)'
    r'(?:\s+[NSEW](?:orth|outh|ast|est)?)?'
    r'(?:,\s*[A-Za-z][A-Za-z\s]{1,30}(?:,\s*(?:ON|BC|AB|QC|MB|SK|NS|NB|PE|NL|NT|YT|NU|[A-Z]{2}))?)?',
    re.IGNORECASE
)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MAX_CONTENT = 5000


def _detect_addresses(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for m in _ADDRESS_RE.finditer(text):
        addr = m.group(0).strip().rstrip(",.")
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            results.append(addr)
        if len(results) >= 4:
            break
    return results


def _geocode(address: str) -> dict | None:
    try:
        resp = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": f"PersonalAgent/1.0 ({CONTACT_EMAIL})"},
            timeout=6,
        )
        data = resp.json()
        if data:
            return {
                "address": address,
                "lat": float(data[0]["lat"]),
                "lng": float(data[0]["lon"]),
                "display_name": data[0].get("display_name", address),
            }
    except Exception:
        pass
    return None


def _run_tavily_search(query: str) -> tuple[str, list[dict]]:
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return "Web search unavailable (no TAVILY_API_KEY set).", []
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": 5, "search_depth": "advanced"},
            timeout=15,
        )
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "No results found.", []
        sources = [{"url": r["url"], "title": r.get("title", r["url"])} for r in results]
        parts = [f"Title: {r.get('title','')}\nURL: {r['url']}\n{r.get('content','')[:600]}" for r in results]
        return "\n\n---\n\n".join(parts), sources
    except Exception as e:
        return f"Search error: {e}", []


_MOA_SEARCH_NEED_PROMPT = """\
You prepare web search for a chat assistant (single model or Self-MoA).
Return ONLY JSON: {{"queries": ["short search query", ...]}}

Include 1–3 queries when the answer benefits from live/external facts: salaries, prices,
visa/immigration rules, academic deadlines, company/product status, policies, rates,
schedules, news, comparisons that change over time, "latest"/"current" lookups.
Use empty queries [] when personal context, memory, coding help, or timeless reasoning is enough.
Do not search for pure preference with no factual dependency.

User message: {message}"""


def _inject_search_into_messages(messages: list, search_block: str) -> list:
    """Prepend a web-search text block onto the last user message."""
    if not search_block or not messages:
        return messages
    last = messages[-1]
    raw_content = last.get("content")
    if isinstance(raw_content, list):
        content = [{"type": "text", "text": search_block}] + list(raw_content)
    else:
        content = [
            {"type": "text", "text": search_block},
            {"type": "text", "text": str(raw_content or "")},
        ]
    return messages[:-1] + [{"role": "user", "content": content}]


def _moa_search_queries(message: str) -> tuple[list[str], float]:
    """Decide 0–3 web queries. Returns (queries, classifier_cost)."""
    if not os.getenv("TAVILY_API_KEY"):
        return [], 0.0
    try:
        text, cost = llm_json(
            _MOA_SEARCH_NEED_PROMPT.format(message=message[:1500]),
            model=UTILITY_MODEL,
            max_tokens=120,
        )
        data = json.loads(strip_code_fence(text))
        raw_queries = data.get("queries") or []
        if not isinstance(raw_queries, list):
            return [], cost
        queries: list[str] = []
        seen: set[str] = set()
        for q in raw_queries[:3]:
            q = (q or "").strip()
            if not q:
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(q[:200])
        return queries, cost
    except Exception:
        return [], 0.0


def _run_tavily_searches(queries: list[str]) -> tuple[str, list[dict]]:
    """Run Tavily for each query in parallel. Returns (combined_block, sources)."""
    if not queries:
        return "", []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = list(pool.map(_run_tavily_search, queries))
    blocks: list[str] = []
    sources: list[dict] = []
    for query, (result_text, srcs) in zip(queries, results):
        n_offset = len(sources)
        sources.extend(
            {"n": n_offset + i + 1, "url": s["url"], "title": s.get("title", s["url"])}
            for i, s in enumerate(srcs)
        )
        blocks.append(f"[Web search results for: {query}]\n{result_text}\n[End of web search]")
    return "\n\n".join(blocks), sources


def _reindex_topic_embedding(slug: str, content: str, description: str = "") -> None:
    from .embeddings import embed_bytes
    from .memory import save_topic_embedding

    save_topic_embedding(slug, embed_bytes(f"{slug} {description} {content}".strip()))


_MOA_CONFIDENCE_RE = re.compile(r"Confidence:\s*([01](?:\.\d+)?)\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_moa_confidence(text: str) -> float:
    """Extract trailing Confidence: 0.XX from a proposer draft; default 0.5."""
    matches = list(_MOA_CONFIDENCE_RE.finditer(text or ""))
    if not matches:
        return 0.5
    try:
        v = float(matches[-1].group(1))
    except ValueError:
        return 0.5
    return max(0.0, min(1.0, v))


def _moa_agents_for_run() -> list:
    """Return Self-MoA agents (all GLM). Caller must ensure ZAI_API_KEY is set."""
    return list(MOA_AGENTS)


def _parse_mentions(message: str, all_topics: list[str]) -> list[str]:
    valid = set(all_topics)
    return [m for m in _MENTION_RE.findall(message) if m in valid]


def _extract_saves(text: str) -> list[tuple[str, str]]:
    return _SAVE_RE.findall(text)


def _strip_saves(text: str) -> str:
    return _SAVE_RE.sub("", text).strip()


def _extract_maps(text: str) -> list[dict]:
    seen: set[str] = set()
    results = []
    for m in _MAP_RE.finditer(text):
        query = m.group(1).strip()
        if query not in seen:
            seen.add(query)
            results.append({"name": query, "query": query})
    return results


def _strip_maps(text: str) -> str:
    return _MAP_RE.sub("", text).strip()


# Below this total char count across all session docs we inject the full text
# (short notes / handouts). Above it we retrieve relevant passages instead —
# NotebookLM-style, so textbooks aren't truncated into a useless 80k dump.
_FULL_INJECT_CHARS = 40_000
_RETRIEVE_CHUNK_LIMIT = 16
_RETRIEVE_CONTEXT_CHARS = 48_000


def _rewrite_doc_query(query: str) -> str:
    """Cheap rewrite to expand paraphrases + keep section numbers for retrieval."""
    q = (query or "").strip()
    if len(q) < 12:
        return q
    from .llm import llm_json, strip_code_fence
    from .models import UTILITY_MODEL
    prompt = (
        "Rewrite this question into a short search query for a textbook/PDF. "
        "Keep exercise/section numbers (e.g. 5.5). Add 3–8 key terms. "
        "Return ONLY the search query text, no quotes.\n\n"
        f"Question: {q[:800]}"
    )
    text, _ = llm_json(prompt, model=UTILITY_MODEL, max_tokens=80)
    out = strip_code_fence(text).strip().strip('"').strip("'")
    return out[:400] if out else q


def _session_documents_context(session_id: str, query: str = "") -> str:
    """Build the documents block for the system prompt.

    Small sessions: inject full document text.
    Large sessions (textbooks): retrieve the top relevant passages for `query`
    via hybrid FTS + Gemini embeddings (no local ONNX).
    """
    from .memory import count_session_document_chars

    total_chars = count_session_document_chars(session_id)
    if total_chars == 0:
        return ""

    if total_chars <= _FULL_INJECT_CHARS:
        docs = get_session_documents(session_id, include_text=True, ready_only=True)
        parts: list[str] = []
        used = 0
        for d in docs:
            text = d.get("text") or ""
            if not text.strip():
                continue
            remaining = _FULL_INJECT_CHARS - used
            if remaining <= 0:
                break
            parts.append(f"### {d['name']}\n{text[:remaining]}")
            used += min(len(text), remaining)
        return "\n\n".join(parts)

    # Large corpus → retrieve relevant passages for this turn's question.
    if not (query or "").strip():
        docs = get_session_documents(session_id, include_text=True, ready_only=True)
        heads = []
        for d in docs:
            text = (d.get("text") or "")[:1_500]
            if text.strip():
                heads.append(f"### {d['name']} (excerpt)\n{text}")
        return "\n\n".join(heads)

    # Backfill Gemini embeddings for legacy uploads (async; this turn still uses FTS).
    try:
        from .doc_store import kick_missing_embeddings
        kick_missing_embeddings(session_id)
    except Exception:
        pass

    search_query = query
    try:
        search_query = _rewrite_doc_query(query)
    except Exception:
        search_query = query

    try:
        hits = search_document_chunks(session_id, search_query, limit=_RETRIEVE_CHUNK_LIMIT)
        # Also search original query if rewrite dropped section refs.
        if search_query != query:
            extra = search_document_chunks(session_id, query, limit=_RETRIEVE_CHUNK_LIMIT)
            seen = {h["id"] for h in hits}
            for h in extra:
                if h["id"] not in seen:
                    hits.append(h)
                    seen.add(h["id"])
            hits = hits[:_RETRIEVE_CHUNK_LIMIT]
    except Exception:
        import traceback; traceback.print_exc()
        hits = []

    if not hits:
        # Chunks missing (legacy upload) — degrade to truncated heads, not full dump.
        docs = get_session_documents(session_id, include_text=True, ready_only=True)
        parts = []
        used = 0
        for d in docs:
            text = d.get("text") or ""
            if not text.strip():
                continue
            remaining = _RETRIEVE_CONTEXT_CHARS - used
            if remaining <= 0:
                parts.append(f"[Additional document \"{d['name']}\" omitted — re-upload to enable retrieval]")
                break
            note = "" if len(text) <= remaining else "\n[...truncated; re-upload this file to enable full retrieval...]"
            parts.append(f"### {d['name']}\n{text[:remaining]}{note}")
            used += min(len(text), remaining)
        return "\n\n".join(parts)

    # Group by document, preserve retrieval rank within each.
    by_doc: dict[str, list[dict]] = {}
    for h in hits:
        by_doc.setdefault(h["doc_name"], []).append(h)

    parts = [
        "The following passages were retrieved from the user's uploaded documents "
        "as most relevant to their current message. Cite the source document and "
        "page number (e.g. name p.42) when using them. If something needed isn't "
        "here, say so — do not invent content."
    ]
    used = 0
    for name, passages in by_doc.items():
        body_bits = []
        for p in passages:
            snippet = p["text"]
            remaining = _RETRIEVE_CONTEXT_CHARS - used
            if remaining <= 0:
                break
            take = snippet[:remaining]
            page = p.get("page")
            label = f"[p.{page}] " if page else ""
            body_bits.append(f"{label}{take}")
            used += len(take)
        if body_bits:
            parts.append(f"### {name}\n" + "\n\n---\n\n".join(body_bits))
    return "\n\n".join(parts)


def _build_system(context: str, summary: str, documents: str = "") -> list[dict]:
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    blocks: list[dict] = [
        {"type": "text", "text": _STATIC_SYSTEM, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Today's date: {today}"},
    ]
    if summary:
        blocks.append({"type": "text", "text": f"## Earlier conversation summary\n\n{summary}"})
    if context:
        blocks.append({"type": "text", "text": f"## Memory\n\n{context}"})
    if documents:
        blocks.append({
            "type": "text",
            "text": (
                "## Attached documents\n\n"
                "The user uploaded the following document(s) to this conversation. "
                "Treat them as authoritative context and refer to them when relevant "
                "throughout the chat. When quoting or answering from a passage, cite "
                "the document name and page (e.g. textbook.pdf p.42) if a page is shown.\n\n"
                + documents
            ),
            # Intentionally no cache_control: retrieved passages change per turn.
        })
    return blocks


def _update_memory(
    topics: list[str], user_msg: str, assistant_msg: str, new_topic: str | None = None
) -> tuple[list[str], float]:
    """Write atomic facts/entities into the knowledge graph. Returns (categories, cost)."""
    from .memory_graph import update_memory_graph

    cats = list(topics or [])
    if new_topic:
        cats.append(new_topic)
    if not cats:
        from .memory_graph import FIXED_CATEGORIES
        cats = list(FIXED_CATEGORIES.keys())
    return update_memory_graph(cats, user_msg, assistant_msg)


def _summarize_messages(msgs: list[dict], existing_summary: str) -> str:
    conversation = "\n".join(
        f"{m['role'].upper()}: {m['content'][:800]}" for m in msgs
    )
    prefix = f"Previous summary:\n{existing_summary}\n\n" if existing_summary else ""
    prompt = (
        f"{prefix}Summarize the key facts and decisions from this conversation for future context. "
        "Be concise (max 300 words). Focus on decisions made, facts established, preferences, tasks.\n\n"
        f"{conversation}"
    )
    resp = _client.messages.create(
        model=UTILITY_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def _maybe_summarize(session_id: str) -> None:
    from .memory import get_messages
    msgs = get_messages(session_id)
    session = get_session(session_id)
    if not session or len(msgs) <= 40:
        return

    summary_count = session["summary_msg_count"]
    to_summarize_through = len(msgs) - 20

    new_msgs_to_cover = msgs[summary_count:to_summarize_through]
    if len(new_msgs_to_cover) < 10:
        return

    new_summary = _summarize_messages(new_msgs_to_cover, session["summary"])
    update_session_summary(session_id, new_summary, to_summarize_through)


# ---------------------------------------------------------------------------
# URL fetching
# ---------------------------------------------------------------------------

def _fetch_via_jina(url: str) -> str | None:
    import os
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/plain, text/markdown",
        "X-Return-Format": "markdown",
    }
    api_key = os.environ.get("JINA_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            timeout=20,
            follow_redirects=True,
            headers=headers,
        )
        if resp.status_code == 200:
            text = resp.text.strip()
            if len(text) > 200:
                return text[:_MAX_CONTENT]
    except Exception:
        pass
    return None


def _fetch_direct(url: str) -> str:
    try:
        resp = httpx.get(
            url,
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,*/*;q=0.8"},
        )
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
            text = "\n".join(lines)
            if len(text) < 200:
                return "[Page returned too little content — likely login-gated or bot-blocked]"
            return text[:_MAX_CONTENT]
        elif "text" in ct or "json" in ct:
            return resp.text[:_MAX_CONTENT]
        else:
            return f"[Non-text content: {ct}]"
    except httpx.HTTPStatusError as e:
        return f"[HTTP {e.response.status_code} — page may require login]"
    except Exception as e:
        return f"[Could not fetch: {e}]"


def _fetch_url_text(url: str) -> str:
    text = _fetch_via_jina(url)
    if text:
        return text
    return _fetch_direct(url)


def _extract_urls(message: str) -> list[str]:
    raw = _URL_RE.findall(message)
    seen: set[str] = set()
    out: list[str] = []
    for u in raw:
        u = u.rstrip(".,;:!?'\")>")
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= 3:
            break
    return out


_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"})


_MAX_ATTACHMENT_THUMB_CHARS = 120_000
_MAX_ATTACHMENT_TEXT_CHARS = 32_000


def _sanitize_attachment(att: dict) -> dict:
    """Keep attachment payloads small for DB + session history API."""
    out: dict = {"name": att["name"], "kind": att["kind"]}
    thumb = att.get("thumb")
    if thumb and len(thumb) <= _MAX_ATTACHMENT_THUMB_CHARS:
        out["thumb"] = thumb
    text = att.get("text")
    if text and att.get("kind") in ("file", "pdf"):
        out["text"] = text[:_MAX_ATTACHMENT_TEXT_CHARS]
    return out


def _build_attachments(req: ChatRequest) -> list[dict]:
    """UI metadata for files/images sent with a user message."""
    if req.attachment_meta:
        return [_sanitize_attachment(a.model_dump()) for a in req.attachment_meta]
    out: list[dict] = []
    for i, data_url in enumerate(req.images):
        if data_url.startswith("data:"):
            att = {"name": f"image-{i + 1}.png", "kind": "image", "thumb": data_url}
            out.append(_sanitize_attachment(att))
    for f in req.files:
        ext = PurePath(f.name).suffix.lstrip(".").lower()
        if ext in _IMAGE_EXTS:
            kind = "image"
        elif ext == "pdf":
            kind = "pdf"
        else:
            kind = "file"
        att: dict = {"name": f.name, "kind": kind}
        if f.thumb:
            att["thumb"] = f.thumb
        if kind in ("file", "pdf") and f.text:
            att["text"] = f.text
        out.append(_sanitize_attachment(att))
    return out


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    # Continue mode: resume a stopped assistant reply (Claude only, non-private).
    is_continue = bool(req.continue_message_id) and not req.private

    if is_continue:
        # History already ends with the partial assistant message; the model
        # continues from it (assistant prefill). No new user turn is added.
        all_topics = []
        relevant_topics = []
        new_topic = None
        update_topics = []
        api_messages, summary = get_api_messages(session_id)
        system = _build_system("", summary, _session_documents_context(session_id, req.message))
    elif req.private:
        # Private mode: no DB, no memory
        all_topics = []
        relevant_topics = []
        new_topic = None
        update_topics = []
        system = _build_system("", "")
        api_messages = [{"role": m.role, "content": m.content} for m in req.history]
    else:
        save_session(session_id)

        all_topics = available_topics()
        mentioned = _parse_mentions(req.message, all_topics)
        relevant_topics, _ = classify(req.message)
        new_topic = None  # fixed category catalog — never invent slugs

        forced = set(mentioned)
        relevant_topics = list(forced | set(relevant_topics))

        update_topics = list(relevant_topics) or ["identity", "ops"]
        from .memory_graph import retrieve_memory
        context = retrieve_memory(req.message, categories=relevant_topics or None)
        api_messages, summary = get_api_messages(session_id)
        system = _build_system(context, summary, _session_documents_context(session_id, req.message))

    # Fetch URLs in message (parallel)
    urls = _extract_urls(req.message)
    url_context = ""
    if urls:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(3, len(urls))) as pool:
            parts = list(pool.map(
                lambda u: f"**URL:** {u}\n{_fetch_url_text(u)}",
                urls,
            ))
        url_context = "\n\n---\n".join(parts)

    from .models import ALLOWED_MODELS, DEFAULT_MODEL
    _MODEL = req.model if req.model in ALLOWED_MODELS else DEFAULT_MODEL
    if is_continue and (_MODEL.startswith("gemini") or _MODEL.startswith("glm")):
        _MODEL = DEFAULT_MODEL  # continuation runs on Claude

    # Claude uses native web_search tools mid-turn. GLM / Gemini / Self-MoA
    # prefetch inside their generators (with a visible "searching" SSE event).
    prefetch_sources: list[dict] = []
    prefetch_cost = 0.0

    user_content: list[dict] = []
    for data_url in req.images:
        if "," in data_url and data_url.startswith("data:"):
            header, b64 = data_url.split(",", 1)
            media_type = header.split(":")[1].split(";")[0]
            user_content.append(
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
            )
    if url_context:
        user_content.append({
            "type": "text",
            "text": f"[Fetched URL content]\n{url_context}\n[End of fetched content]",
        })
    for f in req.files:
        user_content.append({
            "type": "text",
            "text": f"[Attached file: {f.name}]\n{f.text}\n[End of {f.name}]",
        })
    if req.message:
        user_content.append({"type": "text", "text": req.message})

    user_msg_id = None
    if not req.private and not is_continue:
        attachments = _build_attachments(req) or None
        user_msg_id = save_message(session_id, "user", req.message, attachments=attachments)
        session = get_session(session_id)
        if session and not session["title"]:
            update_session_title(session_id, req.message[:60].strip())

    if is_continue:
        # api_messages already ends with the partial assistant reply. Thinking
        # models reject assistant prefill, so we add an explicit user instruction
        # to continue; the streamed continuation is merged into that same message.
        messages_for_api = api_messages + [{
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Continue your previous response exactly from where you left off. "
                        "Do not repeat, re-introduce, or summarize anything you already wrote — "
                        "output only the continuation so it appends seamlessly.",
            }],
        }]
    else:
        messages_for_api = api_messages + [{"role": "user", "content": user_content}]

    # Gmail client-side tools (only added when Gmail is connected)
    def _gmail_tools() -> list[dict]:
        if not gmail_module.get_connection_status()["connected"]:
            return []
        return [
            {
                "name": "list_emails",
                "description": "List recent emails from the user's Gmail inbox. Call this when the user asks about emails, messages, or their inbox.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query e.g. 'is:unread', 'from:boss@co.com', 'subject:invoice'. Empty = most recent."},
                        "max_results": {"type": "integer", "description": "How many emails to return (default 10, max 20)"},
                    },
                },
            },
            {
                "name": "get_email",
                "description": "Read the full body of a specific email by its ID. Use after list_emails.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Email ID from list_emails"},
                    },
                    "required": ["id"],
                },
            },
        ]

    def _run_gmail_tool(name: str, inputs: dict) -> str:
        try:
            if name == "list_emails":
                emails = gmail_module.list_emails(
                    max_results=min(int(inputs.get("max_results", 10)), 20),
                    query=inputs.get("query", ""),
                )
                return json.dumps(emails)
            if name == "get_email":
                return json.dumps(gmail_module.get_email(inputs["id"]))
        except Exception as e:
            return f"Error: {e}"
        return "Unknown tool"

    def generate():
        meta: dict = {
            "type": "start",
            "session_id": session_id,
            "loaded_topics": relevant_topics,
            "user_message_id": user_msg_id,
        }
        if new_topic:
            meta["new_topic"] = new_topic
        if urls:
            meta["fetched_urls"] = urls
        yield f"data: {json.dumps(meta)}\n\n"

        full_text = ""
        chat_cost = 0.0
        search_sources: list[dict] = []
        web_search_tool = {
            "name": "web_search",
            "description": "Search the web for current, up-to-date information. Use for recent news, prices, events, facts, or anything requiring fresh data.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        }
        all_tools = [web_search_tool] + _gmail_tools()
        gmail_tool_names = {"list_emails", "get_email"}
        current_messages = list(messages_for_api)
        final_msg = None

        try:
            while True:
                with _client.messages.stream(
                    model=_MODEL,
                    max_tokens=4096,
                    system=system,
                    messages=current_messages,
                    tools=all_tools,
                ) as stream:
                    for event in stream:
                        etype = getattr(event, "type", None)
                        if etype == "content_block_start":
                            block = getattr(event, "content_block", None)
                            if block and getattr(block, "type", None) == "tool_use":
                                if getattr(block, "name", None) == "web_search":
                                    yield f"data: {json.dumps({'type': 'searching'})}\n\n"
                        elif etype == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta and getattr(delta, "type", None) == "text_delta":
                                full_text += delta.text
                                yield f"data: {json.dumps({'type': 'delta', 'text': delta.text})}\n\n"
                    try:
                        final_msg = stream.get_final_message()
                        chat_cost += _calc_cost(_MODEL, final_msg.usage.input_tokens, final_msg.usage.output_tokens)
                    except Exception:
                        pass

                if not final_msg or final_msg.stop_reason != "tool_use":
                    break
                tool_calls = [b for b in final_msg.content if getattr(b, "type", None) == "tool_use"]
                if not tool_calls:
                    break

                tool_results = []
                for tc in tool_calls:
                    if tc.name == "web_search":
                        result_text, sources = _run_tavily_search(tc.input.get("query", ""))
                        n_offset = len(search_sources)
                        search_sources.extend(
                            {"n": n_offset + i + 1, "url": s["url"], "title": s["title"]}
                            for i, s in enumerate(sources)
                        )
                        tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result_text})
                    elif tc.name in gmail_tool_names:
                        yield f"data: {json.dumps({'type': 'reading_email'})}\n\n"
                        tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": _run_gmail_tool(tc.name, tc.input)})

                current_messages = current_messages + [
                    {"role": "assistant", "content": final_msg.content},
                    {"role": "user", "content": tool_results},
                ]

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        explicit_saves = _extract_saves(full_text)
        clean_text = _strip_saves(full_text) if explicit_saves else full_text

        memory_cost = 0.0
        updated: list[str] = []
        assistant_msg_id = None
        if is_continue:
            # Merge the continuation into the existing stopped message.
            from .memory import get_messages, edit_message
            prior = next((m["content"] for m in get_messages(session_id)
                          if m["id"] == req.continue_message_id), "")
            sep = "" if (prior.endswith(" ") or clean_text.startswith(" ")) else " "
            merged = (prior + sep + clean_text).strip()
            edit_message(session_id, req.continue_message_id, merged)
            assistant_msg_id = req.continue_message_id
        elif not req.private:
            from .memory_graph import FIXED_CATEGORIES, save_explicit_fact
            for slug, fact in explicit_saves:
                if slug in set(all_topics) | set(FIXED_CATEGORIES) | ({new_topic} if new_topic else set()):
                    save_explicit_fact(slug, fact)

            assistant_msg_id = save_message(session_id, "assistant", clean_text)

            if update_topics:
                yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
            try:
                updated, memory_cost = _update_memory(update_topics, req.message, clean_text, new_topic)
            except Exception:
                import traceback; traceback.print_exc()

            updated = list(set(updated) | {s for s, _ in explicit_saves if s in set(all_topics) | set(FIXED_CATEGORIES)})

            try:
                _maybe_summarize(session_id)
            except Exception:
                pass

        # Extract explicit [[MAP:...]] markers the agent placed in its response
        locations = _extract_maps(full_text)
        clean_text = _strip_maps(clean_text)

        total_cost = round(chat_cost + memory_cost, 6)
        cost_bd = {'chat': round(chat_cost, 6), 'memory': round(memory_cost, 6)}
        if assistant_msg_id is not None:
            update_message_meta(assistant_msg_id, _MODEL, total_cost, cost_bd)
        yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg_id, 'updated_topics': updated, 'model': _MODEL, 'cost_usd': total_cost, 'cost_breakdown': cost_bd, 'locations': locations, 'search_sources': search_sources})}\n\n"

    def _emit_start():
        meta = {"type": "start", "session_id": session_id, "loaded_topics": relevant_topics, "user_message_id": user_msg_id}
        if new_topic:
            meta["new_topic"] = new_topic
        if urls:
            meta["fetched_urls"] = urls
        return sse(meta)

    def _merge_continue(sid: str, continue_msg_id: int | None, clean_text: str) -> int | None:
        """Merge a continuation into an existing stopped message; return its id."""
        from .memory import get_messages, edit_message
        prior = next((m["content"] for m in get_messages(sid)
                      if m["id"] == continue_msg_id), "")
        sep = "" if (prior.endswith(" ") or clean_text.startswith(" ")) else " "
        merged = (prior + sep + clean_text).strip()
        edit_message(sid, continue_msg_id, merged)
        return continue_msg_id

    def _save_explicit(explicit_saves, all_topics, new_topic):
        """Persist inline [[SAVE:category:fact]] markers into the knowledge graph."""
        # Accept legacy [[SAVE:phd:...]] aliases via normalize in save_explicit_fact.
        from .memory_graph import CATEGORY_ALIASES, FIXED_CATEGORIES, save_explicit_fact
        valid = set(all_topics) | set(FIXED_CATEGORIES) | set(CATEGORY_ALIASES) | (
            {new_topic} if new_topic else set()
        )
        for slug, fact in explicit_saves:
            if slug in valid or slug in FIXED_CATEGORIES or slug in CATEGORY_ALIASES:
                save_explicit_fact(slug, fact)

    def generate_gemini():
        """Streaming generator for Gemini models."""
        nonlocal prefetch_cost, prefetch_sources
        full_text = ""
        in_tokens = 0
        out_tokens = 0
        yield _emit_start()
        stream_messages = messages_for_api
        if not req.private and not is_continue and os.getenv("TAVILY_API_KEY"):
            queries, q_cost = _moa_search_queries(req.message)
            prefetch_cost += q_cost
            if queries:
                yield sse({"type": "searching"})
                block, prefetch_sources = _run_tavily_searches(queries)
                if block:
                    stream_messages = _inject_search_into_messages(messages_for_api, block)
        try:
            for text, tin, tout in stream_gemini(
                model=_MODEL, messages_for_api=stream_messages, system=system,
            ):
                if text:
                    full_text += text
                    yield sse({"type": "delta", "text": text})
                in_tokens, out_tokens = tin or in_tokens, tout or out_tokens
        except ImportError:
            yield sse({"type": "error", "message": "google-genai package not installed"})
            return
        except RuntimeError as e:
            yield sse({"type": "error", "message": str(e)})
            return
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return
        chat_cost = _calc_cost(_MODEL, in_tokens, out_tokens)
        yield from finalize_stream(
            full_text=full_text, chat_cost=chat_cost,
            is_continue=is_continue, is_private=req.private,
            session_id=session_id, continue_message_id=req.continue_message_id,
            user_message=req.message, all_topics=all_topics, new_topic=new_topic,
            update_topics=update_topics, model_label=_MODEL,
            extract_saves=_extract_saves, strip_saves=_strip_saves,
            extract_maps=_extract_maps, strip_maps=_strip_maps,
            update_memory=_update_memory, maybe_summarize=_maybe_summarize,
            save_assistant=lambda sid, text: save_message(sid, "assistant", text),
            merge_continue=_merge_continue, save_explicit=_save_explicit,
            extra_cost=prefetch_cost,
            search_sources=prefetch_sources,
        )

    def generate_glm():
        """Streaming generator for GLM models, via LiteLLM's Z.ai provider."""
        nonlocal prefetch_cost, prefetch_sources
        full_text = ""
        in_tokens = 0
        out_tokens = 0
        yield _emit_start()
        stream_messages = messages_for_api
        if not req.private and not is_continue and os.getenv("TAVILY_API_KEY"):
            queries, q_cost = _moa_search_queries(req.message)
            prefetch_cost += q_cost
            if queries:
                yield sse({"type": "searching"})
                block, prefetch_sources = _run_tavily_searches(queries)
                if block:
                    stream_messages = _inject_search_into_messages(messages_for_api, block)
        try:
            for text, tin, tout in stream_glm(
                model="zai/glm-5.2",
                messages_for_api=stream_messages, system=system,
            ):
                if text:
                    full_text += text
                    yield sse({"type": "delta", "text": text})
                in_tokens, out_tokens = tin or in_tokens, tout or out_tokens
        except ImportError:
            yield sse({"type": "error", "message": "litellm package not installed"})
            return
        except RuntimeError as e:
            yield sse({"type": "error", "message": str(e)})
            return
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return
        chat_cost = _calc_cost(_MODEL, in_tokens, out_tokens)
        yield from finalize_stream(
            full_text=full_text, chat_cost=chat_cost,
            is_continue=is_continue, is_private=req.private,
            session_id=session_id, continue_message_id=req.continue_message_id,
            user_message=req.message, all_topics=all_topics, new_topic=new_topic,
            update_topics=update_topics, model_label=_MODEL,
            extract_saves=_extract_saves, strip_saves=_strip_saves,
            extract_maps=_extract_maps, strip_maps=_strip_maps,
            update_memory=_update_memory, maybe_summarize=_maybe_summarize,
            save_assistant=lambda sid, t: save_message(sid, "assistant", t),
            merge_continue=_merge_continue, save_explicit=_save_explicit,
            extra_cost=prefetch_cost,
            search_sources=prefetch_sources,
        )

    def generate_moa():
        """Self-MoA: parallel GLM proposers (Advocate / Skeptic / Operator) → GLM synthesis."""
        import queue
        from concurrent.futures import ThreadPoolExecutor

        if not os.getenv("ZAI_API_KEY"):
            yield sse({"type": "error", "message": "ZAI_API_KEY not configured (required for Self-MoA)"})
            return

        moa_agents = _moa_agents_for_run()
        n_agents = len(moa_agents)

        meta = {"type": "start", "session_id": session_id, "loaded_topics": relevant_topics, "user_message_id": user_msg_id}
        if new_topic:
            meta["new_topic"] = new_topic
        if urls:
            meta["fetched_urls"] = urls
        yield sse(meta)

        # Decision-aware web search before proposers (visible in UI as "searching").
        moa_search_block = ""
        moa_search_sources: list[dict] = []
        moa_search_cost = 0.0
        if not req.private and os.getenv("TAVILY_API_KEY"):
            queries, moa_search_cost = _moa_search_queries(req.message)
            if queries:
                yield sse({"type": "searching"})
                moa_search_block, moa_search_sources = _run_tavily_searches(queries)

        proposer_messages = _inject_search_into_messages(messages_for_api, moa_search_block)

        yield sse({"type": "moa_brainstorm"})

        system_str = flatten_system(system)
        agents_cost = prefetch_cost + moa_search_cost
        event_q: queue.Queue = queue.Queue()
        # persona -> {text, model, in_tok, out_tok, error}
        results: dict[str, dict] = {}

        def _run_proposer(agent) -> None:
            persona = agent.persona
            model_id = agent.model
            agent_system = (
                f"{system_str}\n\n"
                f"You are one of {n_agents} agents proposing in parallel "
                f"(roles: {', '.join(a.persona for a in moa_agents)}). "
                f"You do not see the others' drafts.\n\n"
                f"Your role ({persona}): {agent.instruction}\n\n"
                "If web search results are included in the user message, use them when relevant "
                "and cite with [n] where possible. Do not invent live facts you were not given.\n\n"
                f"{MOA_CONFIDENCE_FOOTER}"
            )
            event_q.put(("start", persona, model_id, None))
            full = ""
            in_tok = out_tok = 0
            try:
                for text, tin, tout in stream_glm(
                    model=MOA_GLM_API_MODEL,
                    messages_for_api=proposer_messages,
                    system=agent_system,
                    temperature=agent.temperature,
                ):
                    if text:
                        full += text
                        event_q.put(("delta", persona, model_id, text))
                    in_tok, out_tok = tin or in_tok, tout or out_tok
            except Exception as e:
                full = f"[Error: {e}]"
            results[persona] = {
                "text": full,
                "model": model_id,
                "in_tok": in_tok,
                "out_tok": out_tok,
            }
            conf = _parse_moa_confidence(full) if not full.startswith("[Error") else None
            event_q.put(("done", persona, model_id, conf))

        with ThreadPoolExecutor(max_workers=n_agents) as pool:
            for agent in moa_agents:
                pool.submit(_run_proposer, agent)

            done_count = 0
            while done_count < n_agents:
                kind, persona, model_id, payload = event_q.get()
                if kind == "start":
                    yield sse({"type": "moa_agent_start", "moa_persona": persona, "moa_model": model_id})
                elif kind == "delta":
                    yield sse({
                        "type": "moa_draft_delta",
                        "moa_persona": persona,
                        "moa_model": model_id,
                        "moa_text": payload,
                    })
                elif kind == "done":
                    done_evt: dict = {"type": "moa_agent_done", "moa_persona": persona, "moa_model": model_id}
                    if payload is not None:
                        done_evt["moa_confidence"] = payload
                    yield sse(done_evt)
                    done_count += 1

        # Preserve role order from MOA_AGENTS
        drafts: list[tuple[str, str, str, float]] = []
        for agent in moa_agents:
            r = results.get(agent.persona) or {"text": "[Error: no result]", "model": agent.model, "in_tok": 0, "out_tok": 0}
            text = r["text"]
            model_id = r["model"]
            agents_cost += _calc_cost(model_id, r.get("in_tok", 0), r.get("out_tok", 0))
            conf = _parse_moa_confidence(text) if not text.startswith("[Error") else 0.5
            drafts.append((agent.persona, text, model_id, conf))

        valid = [(p, t, m, c) for p, t, m, c in drafts if t and not t.startswith("[Error")]
        if not valid:
            errors = "; ".join(t for _, t, _, _ in drafts)
            yield f"data: {json.dumps({'type': 'error', 'message': f'All agents failed: {errors}'})}\n\n"
            return

        yield sse({"type": "moa_synthesizing", "moa_model": MOA_SYNTHESIS_MODEL})

        draft_block = "\n\n".join(
            f'<agent name="{p}" confidence="{c:.2f}">\n{t}\n</agent>'
            for p, t, _, c in drafts
        )
        role_names = ", ".join(a.persona for a in moa_agents)
        search_section = (
            f"\n\n<web_search>\n{moa_search_block}\n</web_search>\n"
            if moa_search_block
            else "\n\n<web_search>No live web search was run for this question.</web_search>\n"
        )
        synthesis_msg = (
            f"{n_agents} agents ({role_names}) proposed independently in parallel on the user's "
            "query (Self-MoA). Each ends with a Confidence score (0–1). Synthesize the best "
            "unified answer: weight agreement by confidence, keep the strongest recommendation, "
            "honor valid critiques, include one concrete next step, and surface dissent "
            "explicitly rather than averaging disagreements away. Prefer claims grounded in "
            "web_search when present; cite with [n] when useful. Do not invent Confidence lines "
            "in your final answer.\n\n"
            f"<user_query>{req.message}</user_query>"
            f"{search_section}\n"
            f"<proposals>\n{draft_block}\n</proposals>"
        )

        full_text = ""
        chat_cost = 0.0
        synth_in = synth_out = 0
        try:
            for text, tin, tout in stream_glm(
                model=MOA_GLM_API_MODEL,
                messages_for_api=[{"role": "user", "content": synthesis_msg}],
                system=system,
                temperature=0.5,
            ):
                if text:
                    full_text += text
                    yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
                synth_in, synth_out = tin or synth_in, tout or synth_out
            chat_cost = _calc_cost(MOA_SYNTHESIS_MODEL, synth_in, synth_out)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        explicit_saves = _extract_saves(full_text)
        clean_text = _strip_saves(full_text) if explicit_saves else full_text
        memory_cost = 0.0
        updated: list[str] = []
        assistant_msg_id = None
        if not req.private:
            from .memory_graph import FIXED_CATEGORIES, save_explicit_fact
            for slug, fact in explicit_saves:
                if slug in set(all_topics) | set(FIXED_CATEGORIES) | ({new_topic} if new_topic else set()):
                    save_explicit_fact(slug, fact)
            drafts_for_db = [
                {"persona": p, "text": t, "model": m, "done": True, "confidence": c}
                for p, t, m, c in drafts
                if not t.startswith("[Error")
            ]
            assistant_msg_id = save_message(session_id, "assistant", clean_text, moa_drafts=drafts_for_db or None)
            if update_topics:
                yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
            try:
                updated, memory_cost = _update_memory(update_topics, req.message, clean_text, new_topic)
            except Exception:
                pass
            updated = list(set(updated) | {s for s, _ in explicit_saves if s in set(all_topics) | set(FIXED_CATEGORIES)})
            try:
                _maybe_summarize(session_id)
            except Exception:
                pass

        locations = _extract_maps(full_text)
        clean_text = _strip_maps(clean_text)
        total_cost = round(agents_cost + chat_cost + memory_cost, 6)
        import logging as _log
        _log.getLogger(__name__).info(
            "Self-MoA cost: agents=%.6f synth=%.6f memory=%.6f total=%.6f",
            agents_cost, chat_cost, memory_cost, total_cost,
        )
        cost_bd = {"chat": round(agents_cost + chat_cost, 6), "memory": round(memory_cost, 6)}
        if assistant_msg_id is not None:
            update_message_meta(assistant_msg_id, 'moa', total_cost, cost_bd)
        yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg_id, 'updated_topics': updated, 'model': 'moa', 'cost_usd': total_cost, 'cost_breakdown': cost_bd, 'locations': locations, 'search_sources': moa_search_sources})}\n\n"

    if is_continue:
        # Continuation always uses the standard Claude generator (it holds the merge logic).
        generator = generate()
    elif req.multi_agent:
        generator = generate_moa()
    elif _MODEL.startswith("gemini"):
        generator = generate_gemini()
    elif _MODEL.startswith("glm"):
        generator = generate_glm()
    else:
        generator = generate()

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# File extraction (Gemini multimodal — see backend/file_extract.py)
# ---------------------------------------------------------------------------

@app.post("/files/extract")
async def extract_file(file: UploadFile = File(...)):
    from .file_extract import extract_file_bytes

    data = await file.read()
    name = file.filename or "attachment"
    size_kb = round(len(data) / 1024, 1)

    try:
        text, extract_cost = extract_file_bytes(data, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    if not text.strip():
        raise HTTPException(status_code=400, detail="No content extracted from file")

    return {
        "filename": name,
        "text": text,
        "chars": len(text),
        "size_kb": size_kb,
        "cost_usd": extract_cost,
    }


def _doc_kind(name: str) -> str:
    ext = PurePath(name).suffix.lstrip(".").lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext == "pdf":
        return "pdf"
    return "file"


# ---------------------------------------------------------------------------
# Session documents — persist for the whole conversation, injected every turn
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/documents")
def session_documents_list(session_id: str):
    return {"documents": get_session_documents(session_id, include_text=False)}


@app.post("/sessions/{session_id}/documents")
async def session_document_add(session_id: str, file: UploadFile = File(...)):
    """Accept the original file to disk and return immediately.

    Extraction + chunk indexing runs in a background thread so a textbook
    upload can't OOM/timeout the HTTP request (ChatGPT/Claude style).
    """
    from pathlib import PurePath
    from .doc_store import save_bytes, start_ingest
    from .file_extract import _MAX_INLINE_BYTES, _MAX_PDF_BYTES
    from .memory import update_session_document

    data = await file.read()
    name = file.filename or "attachment"
    size_kb = round(len(data) / 1024, 1)
    ext = PurePath(name).suffix.lstrip(".").lower()
    limit = _MAX_PDF_BYTES if ext == "pdf" else _MAX_INLINE_BYTES
    if len(data) > limit:
        mb = len(data) // (1024 * 1024)
        cap = limit // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({mb} MB; max {cap} MB for .{ext or 'unknown'})",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    doc = add_session_document(
        session_id=session_id,
        name=name,
        kind=_doc_kind(name),
        size_kb=size_kb,
        status="processing",
    )
    try:
        rel = save_bytes(session_id, doc["id"], name, data)
        update_session_document(doc["id"], storage_path=rel)
        doc["storage_path"] = rel
    except Exception as e:
        delete_session_document(session_id, doc["id"])
        raise HTTPException(status_code=500, detail=f"Could not store file: {e}")

    start_ingest(doc["id"])
    return doc


@app.delete("/sessions/{session_id}/documents/{doc_id}")
def session_document_delete(session_id: str, doc_id: int):
    if not delete_session_document(session_id, doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@app.post("/sessions/{session_id}/documents/{doc_id}/reindex")
def session_document_reindex(session_id: str, doc_id: int):
    """Re-chunk + Gemini-embed an already-extracted document (no re-OCR)."""
    from .doc_store import start_reindex
    from .memory import get_session_document, update_session_document

    doc = get_session_document(doc_id)
    if not doc or doc.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="Document not found")
    if not (doc.get("text") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="No extracted text — re-upload the file instead",
        )
    update_session_document(doc_id, status="processing", error="Reindexing…")
    start_reindex(doc_id)
    return get_session_document(doc_id) or doc


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.get("/sessions", response_model=list[SessionInfo])
def sessions_list():
    return [
        SessionInfo(
            session_id=s["session_id"],
            title=s["title"] or "New conversation",
            message_count=s["message_count"],
        )
        for s in list_sessions()
    ]


@app.get("/sessions/search")
def sessions_search(q: str):
    return {"results": search_sessions(q)}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    from .memory import get_messages
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = get_messages(session_id)
    return {"messages": [{"id": m["id"], "role": m["role"], "content": m["content"], "moa_drafts": m.get("moa_drafts"), "model": m.get("model"), "cost_usd": m.get("cost_usd"), "cost_breakdown": m.get("cost_breakdown"), "attachments": m.get("attachments")} for m in msgs]}


@app.patch("/sessions/{session_id}/messages/{msg_id}")
def message_edit(session_id: str, msg_id: int, body: dict):
    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content required")
    if not edit_message(session_id, msg_id, content):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


@app.delete("/sessions/{session_id}/messages/{msg_id}")
def message_delete(session_id: str, msg_id: int):
    if not delete_message(session_id, msg_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


@app.post("/sessions/{session_id}/messages")
def append_message(session_id: str, body: dict):
    """Append a message (used to persist a partial assistant reply after the
    user hits Stop, since the streaming generator never reached its save)."""
    role = body.get("role", "assistant")
    content = (body.get("content") or "").strip()
    if role not in ("assistant", "user") or not content:
        raise HTTPException(status_code=400, detail="role and content required")
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    msg_id = save_message(session_id, role, content)
    return {"ok": True, "id": msg_id}


@app.patch("/sessions/{session_id}")
def session_rename(session_id: str, body: dict):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    update_session_title(session_id, title[:120])
    return {"ok": True}


@app.delete("/sessions/{session_id}")
def session_delete(session_id: str):
    if not delete_session_db(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.post("/feedback")
def feedback(body: dict):
    """Capture 👍/👎 on an assistant reply. Down-votes and notes are written to
    the `feedback` memory topic so future answers can learn; bare up-votes are
    acknowledged but not persisted (keeps the signal high)."""
    rating = body.get("rating")
    if rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")
    note = (body.get("note") or "").strip()
    excerpt = (body.get("message") or "").strip().replace("\n", " ")[:100]

    if rating == "up" and not note:
        return {"ok": True, "stored": False}

    from .memory import get_topic, save_topic, save_topic_embedding
    from .embeddings import embed_bytes

    existing = (get_topic("feedback") or {}).get("content", "")
    icon = "👍" if rating == "up" else "👎"
    date = _dt.date.today().isoformat()
    entry = f"- [{date}] {icon} " + (note if note else "unhelpful response")
    if excerpt:
        entry += f' (re: "{excerpt}")'
    new_content = f"{existing}\n{entry}".strip()
    save_topic("feedback", new_content, description="User feedback on assistant replies")
    try:
        save_topic_embedding("feedback", embed_bytes(f"feedback {new_content}"))
    except Exception:
        pass
    return {"ok": True, "stored": True}


# ---------------------------------------------------------------------------
# Topics / memory graph
# ---------------------------------------------------------------------------

@app.get("/topics")
def topics_list():
    from .memory_graph import category_summaries
    return {"topics": category_summaries()}


class TopicBody(BaseModel):
    content: str = ""
    description: str = ""


class CreateTopicBody(BaseModel):
    description: str = ""


class FactBody(BaseModel):
    text: str
    category: str = "projects"


class FactUpdateBody(BaseModel):
    text: str


@app.get("/memory/facts")
def memory_facts_list(category: str | None = None):
    from .memory_graph import list_facts
    return {"facts": list_facts(category)}


@app.get("/memory/core")
def memory_core_get():
    from .memory_graph import get_core_profile
    return {"content": get_core_profile()}


@app.put("/memory/core")
def memory_core_put(body: TopicBody):
    from .memory_graph import set_core_profile
    set_core_profile(body.content or "")
    return {"ok": True}


@app.put("/memory/facts/{fact_id}")
def memory_fact_update(fact_id: int, body: FactUpdateBody):
    from .memory_graph import update_fact_text
    if not update_fact_text(fact_id, body.text):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"ok": True}


@app.delete("/memory/facts/{fact_id}")
def memory_fact_delete(fact_id: int):
    from .memory_graph import delete_fact
    if not delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"ok": True}


@app.post("/memory/facts")
def memory_fact_add(body: FactBody):
    from .memory_graph import add_fact, save_explicit_fact
    cat = save_explicit_fact(body.category, body.text)
    return {"ok": True, "category": cat}


@app.get("/memory/entities")
def memory_entities_list():
    from .memory_graph import list_entities
    return {"entities": list_entities()}


@app.get("/memory/entities/{entity_id}/neighbors")
def memory_entity_neighbors(entity_id: int):
    from .memory_graph import entity_neighbors
    return {"neighbors": entity_neighbors(entity_id)}


@app.post("/memory/migrate")
def memory_migrate():
    from .memory_graph import migrate_topic_blobs_to_graph
    return migrate_topic_blobs_to_graph()


@app.get("/topics/search")
def topics_search(q: str):
    from .memory_graph import list_facts
    qlow = (q or "").lower()
    hits = []
    for f in list_facts(limit=300):
        if qlow in f["text"].lower() or qlow in f["category"]:
            hits.append({"slug": f["category"], "snippet": f["text"][:120], "fact_id": f["id"]})
        if len(hits) >= 20:
            break
    return {"results": hits}


@app.get("/topics/semantic-search")
def topics_semantic_search(q: str):
    from .memory_graph import retrieve_memory, _search_facts
    facts = _search_facts(q, limit=12)
    return {
        "results": [
            {"slug": f["category"], "score": 1.0 - i * 0.05, "snippet": f["text"][:160]}
            for i, f in enumerate(facts)
        ]
    }


@app.post("/topics/reindex")
def topics_reindex():
    """Re-embed all active facts with Gemini."""
    from .doc_embeddings import embed_bytes, embed_documents
    from .memory import _get_conn
    from .memory_graph import list_facts

    facts = list_facts(limit=2000)
    if not facts:
        return {"ok": True, "updated": 0}
    texts = [f["text"] for f in facts]
    try:
        vectors = embed_documents(texts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    conn = _get_conn()
    for f, vec in zip(facts, vectors):
        conn.execute(
            "UPDATE memory_facts SET embedding = ? WHERE id = ?",
            (embed_bytes(vec), f["id"]),
        )
    conn.commit()
    return {"ok": True, "updated": len(facts)}


@app.delete("/topics/{slug}")
def topic_delete(slug: str):
    from .memory_graph import FIXED_CATEGORIES
    if slug in FIXED_CATEGORIES:
        raise HTTPException(status_code=400, detail="Cannot delete a fixed category")
    from .memory import delete_topic, get_topic
    if not get_topic(slug):
        raise HTTPException(status_code=404, detail="Topic not found")
    delete_topic(slug)
    return {"ok": True}


@app.get("/topics/{slug}")
def topic_read(slug: str):
    from .memory import get_topic
    from .memory_graph import list_facts
    row = get_topic(slug)
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")
    facts = list_facts(slug)
    return {
        **row,
        "content": "\n".join(f"- {f['text']}" for f in facts),
        "facts": facts,
        "fact_count": len(facts),
    }


@app.put("/topics/{slug}")
def topic_upsert(slug: str, body: TopicBody):
    """Legacy: description update only. Content blobs are no longer written."""
    try:
        from .memory import save_topic
        save_topic(slug, "", body.description)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/topics/{slug}")
def topic_create(slug: str, body: CreateTopicBody | None = None):
    from .memory_graph import FIXED_CATEGORIES
    if slug in FIXED_CATEGORIES:
        return {"ok": True, "slug": slug}
    desc = body.description if body else ""
    try:
        create_topic(slug, desc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "slug": slug}


# ---------------------------------------------------------------------------
# Scheduled Tasks
# ---------------------------------------------------------------------------

class TaskBody(BaseModel):
    title: str
    prompt: str
    schedule: str  # "daily HH:MM" | "weekly DOW HH:MM" | "once YYYY-MM-DDTHH:MM"


@app.get("/tasks")
def tasks_list():
    from .scheduler import parse_schedule
    tasks = list_tasks()
    return {"tasks": [
        {**t, "schedule_label": parse_schedule(t["schedule"])}
        for t in tasks
    ]}


@app.post("/tasks")
def task_create(body: TaskBody):
    from .scheduler import add_task_to_scheduler, next_run_from_schedule
    task_id = str(uuid.uuid4())
    next_run = next_run_from_schedule(body.schedule)
    save_task(task_id, body.title, body.prompt, body.schedule, next_run)
    try:
        add_task_to_scheduler(task_id, body.prompt, body.title, body.schedule)
    except Exception as e:
        print(f"Scheduler add warning: {e}")
    return {"ok": True, "id": task_id, "next_run": next_run}


@app.patch("/tasks/{task_id}")
def task_toggle(task_id: str, body: dict):
    active = bool(body.get("active", True))
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    toggle_task(task_id, active)
    from .scheduler import add_task_to_scheduler, remove_task_from_scheduler
    if active:
        add_task_to_scheduler(task_id, task["prompt"], task["title"], task["schedule"])
    else:
        remove_task_from_scheduler(task_id)
    return {"ok": True}


@app.delete("/tasks/{task_id}")
def task_delete(task_id: str):
    from .scheduler import remove_task_from_scheduler
    remove_task_from_scheduler(task_id)
    if not delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------

@app.get("/push/vapid-public-key")
def push_vapid_public_key():
    from .push import VAPID_PUBLIC_KEY
    return {"public_key": VAPID_PUBLIC_KEY}


class PushSubscribeBody(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}

@app.post("/push/subscribe")
def push_subscribe(body: PushSubscribeBody):
    from .memory import save_push_subscription
    save_push_subscription(
        endpoint=body.endpoint,
        p256dh=body.keys.get("p256dh", ""),
        auth=body.keys.get("auth", ""),
    )
    return {"ok": True}

@app.delete("/push/subscribe")
def push_unsubscribe(body: PushSubscribeBody):
    from .memory import delete_push_subscription
    delete_push_subscription(body.endpoint)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reflect
# ---------------------------------------------------------------------------

@app.post("/reflect")
def reflect():
    from .memory_graph import consolidate_graph
    result = consolidate_graph()
    return {
        "ok": True,
        "updated": result.get("updated") or [],
        "merged": result.get("merged", 0),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True, "topics": available_topics()}


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

@app.get("/auth/gmail/start")
def gmail_auth_start():
    try:
        url = gmail_module.get_auth_url()
        return {"url": url}
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))


@app.get("/auth/gmail/callback")
def gmail_auth_callback(code: str, state: str = ""):
    try:
        email = gmail_module.exchange_code(code, state)
        from fastapi.responses import RedirectResponse
        frontend = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
        return RedirectResponse(url=f"{frontend}/?gmail=connected&email={email}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/auth/gmail/status")
def gmail_status():
    return gmail_module.get_connection_status()


@app.delete("/auth/gmail/disconnect")
def gmail_disconnect():
    gmail_module.disconnect()
    return {"ok": True}


class EmailQuery(BaseModel):
    q: str = ""
    max_results: int = 20


@app.get("/emails")
def list_emails(q: str = "", max_results: int = 20):
    try:
        return {"emails": gmail_module.list_emails(max_results=max_results, query=q)}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/{msg_id}")
def get_email(msg_id: str):
    try:
        return gmail_module.get_email(msg_id)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
