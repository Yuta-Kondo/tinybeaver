"""Classify user messages into fixed memory categories (no inventing new slugs)."""
from __future__ import annotations

import json

from .llm import anthropic_client, strip_code_fence
from .memory_graph import FIXED_CATEGORIES
from .models import UTILITY_MODEL


def _topic_section() -> str:
    lines = [
        f"- [{slug}] — {desc}" for slug, desc in sorted(FIXED_CATEGORIES.items())
    ]
    return "Categories:\n" + "\n".join(lines)


_PROMPT = """\
You classify a user message into personal-memory categories for Yuta.

{topic_section}

Message: {message}

Reply with ONLY a JSON object:
- "relevant": array of category slugs from the list above that apply (0–4 items)
- "new_topic": always null (new categories are not allowed)

Example: {{"relevant": ["phd", "finance"], "new_topic": null}}
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
        # Light semantic boost via fact embeddings is done at retrieve time.
        return relevant, None
    except Exception:
        return [], None
