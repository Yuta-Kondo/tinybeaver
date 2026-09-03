"""Classify user messages into MECE life-domain memory categories."""
from __future__ import annotations

import json

from .llm import anthropic_client, strip_code_fence
from .memory_graph import FIXED_CATEGORIES, RESOLVER_ORDER
from .models import UTILITY_MODEL


def _topic_section() -> str:
    lines = [
        f"- [{slug}] — {FIXED_CATEGORIES[slug]}"
        for slug in RESOLVER_ORDER
        if slug in FIXED_CATEGORIES
    ]
    return "Categories (MECE life domains):\n" + "\n".join(lines)


_PROMPT = """\
You classify a user message into personal-memory categories for Yuta.

{topic_section}

Resolver (if ambiguous, pick the earliest that fits):
identity → admin → career → money → home → body → people → craft → play → ops → misc
Rules:
- career = work / research / jobs; admin = legal / government paperwork
- ops = how the assistant should behave; identity = who Yuta is
- misc only if nothing else fits
- Do NOT invent new category slugs

Message: {message}

Reply with ONLY a JSON object:
- "relevant": array of category slugs from the list above (0–4 items)
- "new_topic": always null

Example: {{"relevant": ["career", "admin"], "new_topic": null}}
"""


def classify(message: str) -> tuple[list[str], str | None]:
    """Return (relevant_categories, None). Never invents new topic slugs."""
    topics = list(FIXED_CATEGORIES.keys())
    if not topics:
        return [], None
    try:
        resp = anthropic_client().messages.create(
            model=UTILITY_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    topic_section=_topic_section(),
                    message=message[:2000],
                ),
            }],
        )
        text = strip_code_fence(resp.content[0].text)
        data = json.loads(text)
        allowed = set(topics)
        relevant = [t for t in data.get("relevant", []) if t in allowed]
        return relevant, None
    except Exception:
        return [], None
