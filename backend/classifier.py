from __future__ import annotations

import json

import anthropic

from .memory import topic_descriptions

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


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
        resp = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    topic_section=topic_section,
                    message=message[:2000],
                ),
            }],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:]).rsplit("```", 1)[0]
        data = json.loads(text.strip())
        relevant = [t for t in data.get("relevant", []) if t in topics]
        new_topic: str | None = data.get("new_topic") or None
        return relevant, new_topic
    except Exception:
        return [], None
