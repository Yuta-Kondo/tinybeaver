from __future__ import annotations

import json

from .llm import anthropic_client, strip_code_fence
from .memory import topic_descriptions
from .models import UTILITY_MODEL


def _topic_list_with_descriptions() -> tuple[list[str], str]:
    """Return (topic_slugs, formatted_description_string) from the DB."""
    descs = topic_descriptions()
    if not descs:
        return [], ""
    topics = sorted(descs.keys())
    lines = [
        f"- [{slug}] — {desc}" if desc else f"- [{slug}]"
        for slug, desc in sorted(descs.items())
    ]
    return topics, "Topics (with descriptions):\n" + "\n".join(lines)


_PROMPT = """\
You are classifying a user message to determine which personal-memory topic files are relevant.

{topic_section}

Message: {message}

Reply with ONLY a JSON object:
- "relevant": array of existing topic slugs that apply (must be from the list above)
- "new_topic": a new slug (lowercase, hyphens ok) ONLY if the message clearly covers an area \
with NO matching existing topic — otherwise null

Example: {{"relevant": ["phd", "finance"], "new_topic": null}}
"""


def classify(message: str) -> tuple[list[str], str | None]:
    """Return (relevant_existing_topics, new_topic_slug_or_None)."""
    topics, topic_section = _topic_list_with_descriptions()
    if not topics:
        return [], None
    try:
        resp = anthropic_client().messages.create(
            model=UTILITY_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    topic_section=topic_section,
                    message=message[:2000],
                ),
            }],
        )
        text = strip_code_fence(resp.content[0].text)
        data = json.loads(text)
        relevant = [t for t in data.get("relevant", []) if t in topics]
        new_topic: str | None = data.get("new_topic") or None
        return relevant, new_topic
    except Exception:
        return [], None