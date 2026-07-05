"""Shared LLM clients + streaming helpers.

Centralizes provider clients (so they're created once, not in every module)
and the post-stream finalization logic that was copy-pasted across every
generator in ``main.py``.
"""
from __future__ import annotations

import json
from typing import Generator

import anthropic

from .models import UTILITY_MODEL, calc_cost


# ---------------------------------------------------------------------------
# Singleton clients — created lazily on first use.
# ---------------------------------------------------------------------------

_anthropic_client: anthropic.Anthropic | None = None


def anthropic_client() -> anthropic.Anthropic:
    """Return the shared Anthropic client (created once)."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


# ---------------------------------------------------------------------------
# JSON-from-LLM helper — used by memory update, reflect, classifier-style
# callers that expect a JSON object back.
# ---------------------------------------------------------------------------

def llm_json(
    prompt: str,
    *,
    model: str = UTILITY_MODEL,
    max_tokens: int = 4096,
) -> tuple[str, float]:
    """Run a one-shot completion and return (raw_text, cost_usd)."""
    resp = anthropic_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    cost = calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
    text = resp.content[0].text.strip()
    return text, cost


def strip_code_fence(text: str) -> str:
    """Strip a ```...``` fence (optionally tagged ```json) from LLM output."""
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ---------------------------------------------------------------------------
# Stream finalization — eliminates the copy-pasted post-processing block.
# ---------------------------------------------------------------------------

def finalize_stream(
    *,
    full_text: str,
    chat_cost: float,
    # Context needed for memory + DB saves
    is_continue: bool,
    is_private: bool,
    session_id: str,
    continue_message_id: int | None,
    user_message: str,
    all_topics: list[str],
    new_topic: str | None,
    update_topics: list[str],
    model_label: str,
    # Extract helpers (injected so this module doesn't import main)
    extract_saves,
    strip_saves,
    extract_maps,
    strip_maps,
    update_memory,
    maybe_summarize,
    # Save/merge helpers
    save_assistant,
    merge_continue,
    save_explicit,
    extra_cost: float = 0.0,
) -> Generator[str, None, None]:
    """Run the shared post-stream pipeline and yield the ``done`` event.

    This is the single implementation of the save → memory-update →
    map-extract → cost-emit sequence that was previously duplicated in
    ``generate``, ``generate_gemini``, ``generate_glm`` and ``generate_moa``.
    """
    from .memory import edit_message

    explicit_saves = extract_saves(full_text)
    clean_text = strip_saves(full_text) if explicit_saves else full_text

    memory_cost = 0.0
    updated: list[str] = []
    assistant_msg_id = None

    if is_continue:
        assistant_msg_id = merge_continue(session_id, continue_message_id, clean_text)
    elif not is_private:
        save_explicit(explicit_saves, all_topics, new_topic)
        assistant_msg_id = save_assistant(session_id, clean_text)

        if update_topics:
            yield f"data: {json.dumps({'type': 'memory_updating'})}\n\n"
        try:
            updated, memory_cost = update_memory(
                update_topics, user_message, clean_text, new_topic
            )
        except Exception:
            import traceback
            traceback.print_exc()

        updated = list(set(updated) | {
            s for s, _ in explicit_saves if s in set(all_topics)
        })

        try:
            maybe_summarize(session_id)
        except Exception:
            pass

    locations = extract_maps(full_text)
    clean_text = strip_maps(clean_text)

    total_cost = round(chat_cost + memory_cost + extra_cost, 6)
    cost_bd = {
        "chat": round(chat_cost + extra_cost, 6),
        "memory": round(memory_cost, 6),
    }
    if assistant_msg_id is not None:
        from .memory import update_message_meta
        update_message_meta(assistant_msg_id, model_label, total_cost, cost_bd)

    yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg_id, 'updated_topics': updated, 'model': model_label, 'cost_usd': total_cost, 'cost_breakdown': cost_bd, 'locations': locations, 'search_sources': []})}\n\n"


def sse(event: dict) -> str:
    """Serialize an event dict as an SSE ``data:`` line."""
    return f"data: {json.dumps(event)}\n\n"