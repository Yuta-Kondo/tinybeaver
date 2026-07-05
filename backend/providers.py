"""Provider-specific message conversion + streaming.

Each provider has different message/part formats. The conversion helpers here
were previously duplicated inside the generator functions in ``main.py``.

Adding a new provider:
  1. Add a ``convert_<provider>_messages`` function below.
  2. Add a ``stream_<provider>`` function that yields ``(text, in_tokens,
     out_tokens)`` or raises.
  3. Wire it into the dispatch in ``main.py``'s ``chat_stream``.
"""
from __future__ import annotations

import base64
import os
from typing import Generator


# ---------------------------------------------------------------------------
# Anthropic content blocks — the canonical internal format used by main.py.
# (No conversion needed; included here for documentation.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Gemini (google-genai)
# ---------------------------------------------------------------------------

def _to_gemini_parts(content, gtypes):
    """Convert an Anthropic-format content value to a list of Gemini Parts."""
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
                parts.append(gtypes.Part.from_bytes(
                    data=base64.b64decode(src["data"]),
                    mime_type=src.get("media_type", "image/jpeg"),
                ))
    return parts or [gtypes.Part.from_text(text="")]


def convert_gemini_messages(messages_for_api, gtypes):
    """Convert Anthropic-style messages to Gemini ``Content`` objects."""
    out = []
    for msg in messages_for_api:
        role = "model" if msg["role"] == "assistant" else "user"
        out.append(gtypes.Content(role=role, parts=_to_gemini_parts(msg["content"], gtypes)))
    return out


def flatten_system(system) -> str:
    """Flatten an Anthropic system (list of text blocks) to a plain string."""
    if isinstance(system, list):
        return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return system or ""


def stream_gemini(
    *,
    model: str,
    messages_for_api: list[dict],
    system,
    temperature: float = 0.7,
) -> Generator[tuple[str, int, int], None, None]:
    """Yield (delta_text, input_tokens, output_tokens) chunks from Gemini.

    Raises ImportError / RuntimeError if the provider isn't configured.
    """
    from google import genai as google_genai
    from google.genai import types as gtypes

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")

    client = google_genai.Client(api_key=api_key)
    gemini_msgs = convert_gemini_messages(messages_for_api, gtypes)
    config = gtypes.GenerateContentConfig(
        system_instruction=flatten_system(system),
        temperature=temperature,
    )

    in_tokens = 0
    out_tokens = 0
    for chunk in client.models.generate_content_stream(
        model=model, contents=gemini_msgs, config=config,
    ):
        if chunk.text:
            yield chunk.text, 0, 0
        usage = getattr(chunk, "usage_metadata", None)
        if usage:
            in_tokens = getattr(usage, "prompt_token_count", 0) or 0
            out_tokens = getattr(usage, "candidates_token_count", 0) or 0
    # Final usage chunk carries the totals.
    yield "", in_tokens, out_tokens


# ---------------------------------------------------------------------------
# GLM (via LiteLLM's zai/ provider — OpenAI-compatible)
# ---------------------------------------------------------------------------

def _to_glm_content(blocks: list[dict]) -> list[dict]:
    """Convert Anthropic content blocks to OpenAI-style content parts."""
    glm_content = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            glm_content.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image":
            src = block.get("source", {})
            if src.get("type") == "base64" and src.get("data"):
                glm_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{src.get('media_type', 'image/jpeg')};base64,{src['data']}"},
                })
    return glm_content


def convert_glm_messages(messages_for_api: list[dict], system) -> list[dict]:
    """Convert Anthropic-style messages to the OpenAI-style format LiteLLM expects."""
    glm_msgs: list[dict] = []
    for msg in messages_for_api:
        role = msg["role"] if msg["role"] in ("user", "assistant") else "user"
        content = msg["content"]
        if isinstance(content, str):
            glm_msgs.append({"role": role, "content": content})
        elif isinstance(content, list):
            glm_msgs.append({"role": role, "content": _to_glm_content(content)})

    system_str = flatten_system(system)
    if system_str:
        glm_msgs.insert(0, {"role": "system", "content": system_str})
    return glm_msgs


def stream_glm(
    *,
    model: str,
    messages_for_api: list[dict],
    system,
    temperature: float = 0.7,
) -> Generator[tuple[str, int, int], None, None]:
    """Yield (delta_text, input_tokens, output_tokens) chunks from GLM via LiteLLM.

    ``model`` is the LiteLLM-prefixed id, e.g. ``zai/glm-5.2``.
    """
    import litellm

    api_key = os.getenv("ZAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("ZAI_API_KEY not configured")

    glm_msgs = convert_glm_messages(messages_for_api, system)
    response = litellm.completion(
        model=model,
        messages=glm_msgs,
        api_key=api_key,
        stream=True,
        stream_options={"include_usage": True},
        temperature=temperature,
    )
    in_tokens = 0
    out_tokens = 0
    for chunk in response:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content, 0, 0
        if getattr(chunk, "usage", None):
            in_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
            out_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
    yield "", in_tokens, out_tokens