from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .classifier import classify
from . import gmail as gmail_module
from .memory import (
    available_topics,
    create_topic,
    delete_message,
    delete_session_db,
    delete_task,
    edit_message,
    get_api_messages,
    get_session,
    get_task,
    get_topics_content,
    list_sessions,
    list_tasks,
    load_context,
    save_message,
    save_session,
    save_task,
    search_sessions,
    search_topics,
    toggle_task,
    topic_descriptions,
    update_message_meta,
    update_session_summary,
    update_session_title,
    update_task_next_run,
)
from .models import ChatRequest, SessionInfo

app = FastAPI(title="Personal AI Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client = anthropic.Anthropic()

# Pricing per million tokens  (input, output)  — June 2026
# Contact email used in outbound request headers and push VAPID claims.
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "contact@example.com")

_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00,  5.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-8":           (5.00, 25.00),
    "gemini-3.5-flash":          (1.50,  9.00),
}
# Sonnet 5 introductory pricing until Aug 31 2026, standard after
_SONNET5_INTRO = (2.00, 10.00)
_SONNET5_STANDARD = (3.00, 15.00)
_SONNET5_INTRO_END = _dt.date(2026, 8, 31)


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model == "claude-sonnet-5":
        p_in, p_out = _SONNET5_INTRO if _dt.date.today() <= _SONNET5_INTRO_END else _SONNET5_STANDARD
    else:
        p_in, p_out = _PRICING.get(model, (3.00, 15.00))
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)


_STATIC_SYSTEM = """\
You are Yuta's personal AI assistant with access to structured memory about \
his life, work, and goals — PhD program, finances, immigration, housing search, \
and ongoing projects. Speak directly and concisely.

Format responses in Markdown. Use LaTeX for all mathematics \
(inline: $...$, block: $$...$$).

To explicitly save a fact to memory mid-response, write:
[[SAVE:topic_slug:The fact to save.]]
This works for any existing topic slug. Use sparingly — only for personal facts \
about Yuta (preferences, decisions, plans, experiences). Never save general \
knowledge, definitions, or facts that could be looked up online.

When you mention a specific place the user would want to visit (a store, restaurant, \
venue, address), add a map marker on its own line:
[[MAP:Place Name, City]]
Only use this for concrete, visitable places — not general areas or hypothetical addresses.

"""

# ---------------------------------------------------------------------------
# Startup: init DB + scheduler
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    # Touch DB to run migrations
    available_topics()
    # Start task scheduler
    try:
        from .scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler startup warning: {e}")


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


def _build_system(context: str, summary: str) -> list[dict]:
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
    return blocks


def _update_memory(
    topics: list[str], user_msg: str, assistant_msg: str, new_topic: str | None
) -> tuple[list[str], float]:
    """Returns (updated_slugs, cost_usd)."""
    if not topics:
        return [], 0.0

    topic_contents = get_topics_content(topics)
    sections = "\n\n".join(
        f"### {t}\n{c or '(empty)'}" for t, c in topic_contents.items()
    )
    new_topic_note = (
        f"\nNote: '{new_topic}' is a newly created topic with no content. "
        "Populate it from the conversation if relevant."
        if new_topic else ""
    )
    prompt = f"""You are updating Yuta's personal memory files based on a conversation.

Current memory:
{sections}

Conversation:
User: {user_msg[:3000]}
Assistant: {assistant_msg[:1500]}
{new_topic_note}
For each topic that gained new **personal** information about Yuta worth persisting, return updated markdown.
Only save: personal facts, preferences, decisions, plans, experiences, and context specific to Yuta.
Never save: general knowledge, how-to explanations, definitions, or anything that could be looked up online.
Return ONLY a JSON object: {{"topic_slug": "updated content", ...}}
Omit topics with no changes. If nothing changed, return {{}}.
Memory files are concise personal summaries, not transcripts. Do not invent facts."""

    _model = "claude-haiku-4-5-20251001"
    resp = _client.messages.create(
        model=_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    cost = _calc_cost(_model, resp.usage.input_tokens, resp.usage.output_tokens)

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    updates: dict = json.loads(text.strip())
    allowed = set(topics)
    updated: list[str] = []
    for slug, content in updates.items():
        if slug in allowed:
            from .memory import save_topic
            save_topic(slug, content)
            try:
                from .embeddings import embed_bytes
                from .memory import save_topic_embedding
                save_topic_embedding(slug, embed_bytes(f"{slug} {content}"))
            except Exception:
                pass
            updated.append(slug)
    return updated, cost


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
        model="claude-haiku-4-5-20251001",
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
        system = _build_system("", summary)
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
        relevant_topics, new_topic = classify(req.message)

        forced = set(mentioned)
        relevant_topics = list(forced | set(relevant_topics))

        if new_topic:
            try:
                create_topic(new_topic)
            except ValueError:
                new_topic = None

        update_topics = relevant_topics + ([new_topic] if new_topic else [])
        context = load_context(relevant_topics)
        api_messages, summary = get_api_messages(session_id)
        system = _build_system(context, summary)

    # Fetch URLs in message
    urls = _extract_urls(req.message)
    url_context = ""
    if urls:
        parts = []
        for url in urls:
            text = _fetch_url_text(url)
            parts.append(f"**URL:** {url}\n{text}")
        url_context = "\n\n---\n".join(parts)

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
        user_msg_id = save_message(session_id, "user", req.message)
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
    from .models import ALLOWED_MODELS, DEFAULT_MODEL
    _MODEL = req.model if req.model in ALLOWED_MODELS else DEFAULT_MODEL
    if is_continue and _MODEL.startswith("gemini"):
        _MODEL = DEFAULT_MODEL  # continuation runs on Claude

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
            for slug, fact in explicit_saves:
                if slug in set(all_topics) | ({new_topic} if new_topic else set()):
                    from .memory import get_topic, save_topic
                    row = get_topic(slug)
                    existing = row["content"] if row else ""
                    save_topic(slug, f"{existing}\n- {fact}".strip())

            assistant_msg_id = save_message(session_id, "assistant", clean_text)

            if update_topics:
                yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
            try:
                updated, memory_cost = _update_memory(update_topics, req.message, clean_text, new_topic)
            except Exception:
                import traceback; traceback.print_exc()

            updated = list(set(updated) | {s for s, _ in explicit_saves if s in set(all_topics)})

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

    def generate_gemini():
        """Streaming generator for Gemini models."""
        try:
            from google import genai as google_genai
            from google.genai import types as gtypes
        except ImportError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'google-genai package not installed'})}\n\n"
            return

        import os
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            yield f"data: {json.dumps({'type': 'error', 'message': 'GOOGLE_API_KEY not configured'})}\n\n"
            return

        meta = {"type": "start", "session_id": session_id, "loaded_topics": relevant_topics, "user_message_id": user_msg_id}
        if new_topic:
            meta["new_topic"] = new_topic
        if urls:
            meta["fetched_urls"] = urls
        yield f"data: {json.dumps(meta)}\n\n"

        client_g = google_genai.Client(api_key=api_key)

        # Convert messages to Gemini format
        def _to_parts(content):
            if isinstance(content, str):
                return [gtypes.Part.from_text(text=content)]
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                t = block.get("type")
                if t == "text":
                    parts.append(gtypes.Part.from_text(text=block["text"]))
                elif t == "image":
                    src = block.get("source", {})
                    if src.get("type") == "base64":
                        import base64
                        parts.append(gtypes.Part.from_bytes(
                            data=base64.b64decode(src["data"]),
                            mime_type=src.get("media_type", "image/jpeg"),
                        ))
            return parts or [gtypes.Part.from_text(text="")]

        gemini_msgs = []
        for msg in messages_for_api:
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_msgs.append(gtypes.Content(role=role, parts=_to_parts(msg["content"])))

        if isinstance(system, list):
            gemini_system = "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
        else:
            gemini_system = system
        config = gtypes.GenerateContentConfig(
            system_instruction=gemini_system,
            temperature=0.7,
        )

        full_text = ""
        in_tokens = 0
        out_tokens = 0
        try:
            for chunk in client_g.models.generate_content_stream(
                model=_MODEL,
                contents=gemini_msgs,
                config=config,
            ):
                if chunk.text:
                    full_text += chunk.text
                    yield f"data: {json.dumps({'type': 'delta', 'text': chunk.text})}\n\n"
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    in_tokens = getattr(usage, "prompt_token_count", 0) or 0
                    out_tokens = getattr(usage, "candidates_token_count", 0) or 0
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        chat_cost = _calc_cost(_MODEL, in_tokens, out_tokens)

        explicit_saves = _extract_saves(full_text)
        clean_text = _strip_saves(full_text) if explicit_saves else full_text
        memory_cost = 0.0
        updated: list[str] = []
        assistant_msg_id = None
        if not req.private:
            for slug, fact in explicit_saves:
                if slug in set(all_topics) | ({new_topic} if new_topic else set()):
                    from .memory import get_topic, save_topic
                    row = get_topic(slug)
                    existing = row["content"] if row else ""
                    save_topic(slug, f"{existing}\n- {fact}".strip())
            assistant_msg_id = save_message(session_id, "assistant", clean_text)
            if update_topics:
                yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
            try:
                updated, memory_cost = _update_memory(update_topics, req.message, clean_text, new_topic)
            except Exception:
                pass
            updated = list(set(updated) | {s for s, _ in explicit_saves if s in set(all_topics)})
            try:
                _maybe_summarize(session_id)
            except Exception:
                pass

        locations = _extract_maps(full_text)
        clean_text = _strip_maps(clean_text)
        total_cost = round(chat_cost + memory_cost, 6)
        cost_bd = {'chat': round(chat_cost, 6), 'memory': round(memory_cost, 6)}
        if assistant_msg_id is not None:
            update_message_meta(assistant_msg_id, _MODEL, total_cost, cost_bd)
        yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg_id, 'updated_topics': updated, 'model': _MODEL, 'cost_usd': total_cost, 'cost_breakdown': cost_bd, 'locations': locations, 'search_sources': []})}\n\n"

    def generate_moa():
        """MoA: 3 Gemini Flash agents in parallel → Claude Sonnet synthesizer."""
        import os, concurrent.futures

        try:
            from google import genai as google_genai
            from google.genai import types as gtypes
        except ImportError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'google-genai not installed'})}\n\n"
            return

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            yield f"data: {json.dumps({'type': 'error', 'message': 'GOOGLE_API_KEY not configured'})}\n\n"
            return

        meta = {"type": "start", "session_id": session_id, "loaded_topics": relevant_topics, "user_message_id": user_msg_id}
        if new_topic: meta["new_topic"] = new_topic
        if urls: meta["fetched_urls"] = urls
        yield f"data: {json.dumps(meta)}\n\n"
        yield f"data: {json.dumps({'type': 'moa_brainstorm'})}\n\n"

        # Convert Anthropic message format → Gemini
        def _to_parts(content):
            if isinstance(content, str):
                return [gtypes.Part.from_text(text=content)]
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(gtypes.Part.from_text(text=block["text"]))
                elif block.get("type") == "image":
                    src = block.get("source", {})
                    if src.get("type") == "base64":
                        import base64 as _b64
                        parts.append(gtypes.Part.from_bytes(
                            data=_b64.b64decode(src["data"]),
                            mime_type=src.get("media_type", "image/jpeg"),
                        ))
            return parts or [gtypes.Part.from_text(text="")]

        gemini_msgs = [
            gtypes.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=_to_parts(m["content"]),
            )
            for m in messages_for_api
        ]

        # Flatten Anthropic list[dict] system → plain string for Gemini
        if isinstance(system, list):
            system_str = "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
        else:
            system_str = system

        AGENTS = [
            ("Comprehensive", "Explore all aspects thoroughly: background, context, nuance, and implications."),
            ("Concise",       "Cut to the core. Read what was said above, then give the 2-3 most important points directly. Agree, disagree, or add what was missed."),
            ("Critical",      "Challenge assumptions. Read what was said above, then identify edge cases, counterarguments, risks, and what could go wrong."),
        ]

        drafts: list[tuple[str, str]] = []
        flash_cost = 0.0

        for agent_idx, (persona, instruction) in enumerate(AGENTS):
            # Build debate context: show all previous agents' responses
            if drafts:
                prior = "\n\n".join(
                    f"[{p} — Agent {i+1}]\n{t}"
                    for i, (p, t) in enumerate(drafts)
                )
                agent_system = (
                    system_str
                    + f"\n\nYou are Agent {agent_idx + 1} of 3 in a multi-agent discussion. "
                    f"The agents before you have already responded:\n\n{prior}\n\n"
                    f"Your role ({persona}): {instruction}"
                )
            else:
                agent_system = (
                    system_str
                    + f"\n\nYou are Agent 1 of 3 in a multi-agent discussion. "
                    f"Your role ({persona}): {instruction}"
                )

            client_g = google_genai.Client(api_key=api_key)
            cfg = gtypes.GenerateContentConfig(
                system_instruction=agent_system,
                temperature=0.8,
            )
            full = ""
            in_tok = out_tok = 0
            try:
                for chunk in client_g.models.generate_content_stream(
                    model="gemini-3.5-flash", contents=gemini_msgs, config=cfg,
                ):
                    if chunk.text:
                        full += chunk.text
                        yield f"data: {json.dumps({'type': 'moa_draft_delta', 'moa_persona': persona, 'moa_text': chunk.text})}\n\n"
                    u = getattr(chunk, "usage_metadata", None)
                    if u:
                        in_tok = getattr(u, "prompt_token_count", 0) or 0
                        out_tok = getattr(u, "candidates_token_count", 0) or 0
            except Exception as e:
                full = f"[Error: {e}]"
            flash_cost += _calc_cost("gemini-3.5-flash", in_tok, out_tok)
            drafts.append((persona, full))
            yield f"data: {json.dumps({'type': 'moa_agent_done', 'moa_persona': persona})}\n\n"

        valid = [(p, t) for p, t in drafts if t and not t.startswith("[Error")]
        if not valid:
            errors = "; ".join(t for _, t in drafts)
            yield f"data: {json.dumps({'type': 'error', 'message': f'All agents failed: {errors}'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'moa_synthesizing'})}\n\n"

        draft_block = "\n\n".join(f"<agent name=\"{p}\" index=\"{i+1}\">\n{t}\n</agent>" for i, (p, t) in enumerate(drafts))
        synthesis_msg = (
            f"Three agents had a sequential debate about the user's query — each agent read the previous agents' responses before writing their own. "
            f"Now synthesize the best possible unified response: take the strongest insights, incorporate critiques, and resolve any disagreements into a clear, well-structured answer.\n\n"
            f"<user_query>{req.message}</user_query>\n\n"
            f"<debate>\n{draft_block}\n</debate>"
        )

        full_text = ""
        chat_cost = 0.0
        try:
            with _client.messages.stream(
                model="claude-sonnet-5",
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": synthesis_msg}],
            ) as stream:
                for event in stream:
                    if getattr(event, "type", None) == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            full_text += delta.text
                            yield f"data: {json.dumps({'type': 'delta', 'text': delta.text})}\n\n"
                try:
                    final = stream.get_final_message()
                    chat_cost = _calc_cost("claude-sonnet-5", final.usage.input_tokens, final.usage.output_tokens)
                except Exception:
                    pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        explicit_saves = _extract_saves(full_text)
        clean_text = _strip_saves(full_text) if explicit_saves else full_text
        memory_cost = 0.0
        updated: list[str] = []
        assistant_msg_id = None
        if not req.private:
            for slug, fact in explicit_saves:
                if slug in set(all_topics) | ({new_topic} if new_topic else set()):
                    from .memory import get_topic, save_topic
                    row = get_topic(slug)
                    existing = row["content"] if row else ""
                    save_topic(slug, f"{existing}\n- {fact}".strip())
            drafts_for_db = [{"persona": p, "text": t, "done": True} for p, t in drafts if not t.startswith("[Error")]
            assistant_msg_id = save_message(session_id, "assistant", clean_text, moa_drafts=drafts_for_db or None)
            if update_topics:
                yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
            try:
                updated, memory_cost = _update_memory(update_topics, req.message, clean_text, new_topic)
            except Exception:
                pass
            updated = list(set(updated) | {s for s, _ in explicit_saves if s in set(all_topics)})
            try:
                _maybe_summarize(session_id)
            except Exception:
                pass

        locations = _extract_maps(full_text)
        clean_text = _strip_maps(clean_text)
        total_cost = round(flash_cost + chat_cost + memory_cost, 6)
        import logging as _log
        _log.getLogger(__name__).info("MoA cost: flash=%.6f chat=%.6f memory=%.6f total=%.6f", flash_cost, chat_cost, memory_cost, total_cost)
        cost_bd = {'chat': round(flash_cost + chat_cost, 6), 'memory': round(memory_cost, 6)}
        if assistant_msg_id is not None:
            update_message_meta(assistant_msg_id, 'moa', total_cost, cost_bd)
        yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg_id, 'updated_topics': updated, 'model': 'moa', 'cost_usd': total_cost, 'cost_breakdown': cost_bd, 'locations': [], 'search_sources': []})}\n\n"

    if is_continue:
        # Continuation always uses the standard Claude generator (it holds the merge logic).
        generator = generate()
    elif req.multi_agent:
        generator = generate_moa()
    elif _MODEL.startswith("gemini"):
        generator = generate_gemini()
    else:
        generator = generate()

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# File extraction
# ---------------------------------------------------------------------------

def _llm_clean_pdf(raw: str, filename: str) -> tuple[str, float]:
    """Returns (cleaned_text, cost_usd)."""
    if len(raw) < 200:
        return raw, 0.0
    _model = "claude-haiku-4-5-20251001"
    resp = _client.messages.create(
        model=_model,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": (
                f"The following is raw text extracted from a PDF file called '{filename}'. "
                "Clean it up: fix OCR artifacts, remove page headers/footers/page numbers, "
                "reformat any tables as Markdown tables, preserve document structure with "
                "proper headings, and make it readable. Return ONLY the cleaned text, no commentary.\n\n"
                f"{raw[:15000]}"
            ),
        }],
    )
    cost = _calc_cost(_model, resp.usage.input_tokens, resp.usage.output_tokens)
    return resp.content[0].text.strip(), cost


@app.post("/files/extract")
async def extract_file(file: UploadFile = File(...)):
    data = await file.read()
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    try:
        if ext == "pdf":
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = [p.extract_text() or "" for p in reader.pages]
            raw = "\n\n".join(p.strip() for p in pages if p.strip())
            if not raw.strip():
                raise HTTPException(status_code=400, detail="No text found in PDF — it may be scanned/image-only")
            text, extract_cost = _llm_clean_pdf(raw, name)
        elif ext == "csv":
            import csv
            raw = data.decode("utf-8", errors="replace")
            rows = list(csv.reader(io.StringIO(raw)))
            extract_cost = 0.0
            if rows and len(rows) <= 200:
                header = rows[0]
                sep = ["---"] * len(header)
                body = rows[1:]
                lines = [
                    "| " + " | ".join(header) + " |",
                    "| " + " | ".join(sep) + " |",
                ] + ["| " + " | ".join(r) + " |" for r in body]
                text = "\n".join(lines)
            else:
                text = "\n".join(", ".join(r) for r in rows)
        else:
            text = data.decode("utf-8", errors="replace")
            extract_cost = 0.0
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not extract text: {e}")

    if not text.strip():
        raise HTTPException(status_code=400, detail="No text content found in file")

    size_kb = round(len(data) / 1024, 1)
    return {"filename": name, "text": text[:20000], "chars": len(text), "size_kb": size_kb, "cost_usd": extract_cost}


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
    return {"messages": [{"id": m["id"], "role": m["role"], "content": m["content"], "moa_drafts": m.get("moa_drafts"), "model": m.get("model"), "cost_usd": m.get("cost_usd"), "cost_breakdown": m.get("cost_breakdown")} for m in msgs]}


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
# Topics
# ---------------------------------------------------------------------------

@app.get("/topics")
def topics_list():
    descs = topic_descriptions()
    return {"topics": [{"slug": slug, "description": desc} for slug, desc in descs.items()]}


class TopicBody(BaseModel):
    content: str
    description: str = ""


class CreateTopicBody(BaseModel):
    description: str = ""


@app.get("/topics/search")
def topics_search(q: str):
    return {"results": search_topics(q)}


@app.get("/topics/semantic-search")
def topics_semantic_search(q: str):
    try:
        from .embeddings import semantic_search
        return {"results": semantic_search(q)}
    except Exception as e:
        return {"results": [], "error": str(e)}


@app.post("/topics/reindex")
def topics_reindex():
    try:
        from .embeddings import reindex_all
        count = reindex_all()
        return {"ok": True, "updated": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/topics/{slug}")
def topic_read(slug: str):
    from .memory import get_topic
    row = get_topic(slug)
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")
    return row


@app.put("/topics/{slug}")
def topic_upsert(slug: str, body: TopicBody):
    try:
        from .memory import save_topic
        save_topic(slug, body.content, body.description)
        # Reindex embedding
        try:
            from .embeddings import embed_bytes
            from .memory import save_topic_embedding
            save_topic_embedding(slug, embed_bytes(f"{slug} {body.description} {body.content}"))
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/topics/{slug}")
def topic_create(slug: str, body: CreateTopicBody | None = None):
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
    topics = available_topics()
    if not topics:
        return {"ok": True, "updated": []}

    contents = get_topics_content(topics)
    non_empty = {t: c for t, c in contents.items() if c.strip()}
    if not non_empty:
        return {"ok": True, "updated": []}

    sections = "\n\n".join(f"### {t}\n{c}" for t, c in non_empty.items())
    prompt = f"""Review Yuta's personal memory files and improve them.

{sections}

Tasks:
1. Remove duplicate or redundant facts
2. Consolidate scattered notes about the same subject into clean bullet points
3. Improve conciseness — facts only, no filler
4. Do NOT invent facts, add speculation, or change the meaning

Return ONLY a JSON object: {{"slug": "revised content", ...}}
Only include topics that need changes. If all looks good, return {{}}."""

    resp = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]

    updates: dict = json.loads(text.strip())
    updated: list[str] = []
    from .memory import save_topic
    for slug, content in updates.items():
        if slug in topics:
            save_topic(slug, content)
            updated.append(slug)
    return {"ok": True, "updated": updated}


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
        return RedirectResponse(url=f"http://localhost:5173/?gmail=connected&email={email}")
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
