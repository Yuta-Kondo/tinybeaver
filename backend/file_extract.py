"""LLM-based file extraction via Gemini native multimodal (PDF, images, spreadsheets).

Sends files inline to Gemini in a single request — same pattern as the Gemini app,
not per-page rasterization or separate Sonnet calls.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import PurePath

from .models import FILE_EXTRACTION_MODEL, calc_cost

_log = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"})
_TEXT_EXTS = frozenset({"csv", "txt", "md", "json", "tsv", "log", "xml", "html", "htm"})
_EXCEL_EXTS = frozenset({"xlsx", "xlsm"})
# Google Gemini inline limits: PDFs 50 MB; other inline types up to 100 MB per request.
_MAX_PDF_BYTES = 50 * 1024 * 1024
_MAX_INLINE_BYTES = 100 * 1024 * 1024
_MAX_OUTPUT_CHARS = 80_000

_EXTRACT_PROMPT = """\
You are extracting the full content of a file attachment for a personal AI assistant.

Filename: {filename}
Type: {kind}

Rules:
- Output clean Markdown preserving ALL meaningful content (text, numbers, tables, labels).
- Tables → Markdown tables with headers when possible.
- Images/diagrams → transcribe visible text (OCR) and briefly note non-text visuals.
- Spreadsheets → preserve every row and column; one section per sheet.
- PDFs → extract all pages; preserve structure, headings, tables, and figure captions.
- Do NOT add commentary, preamble, or "here is the content" — output ONLY the extracted material.
- Prefer completeness over summarization."""


def _mime_for_ext(ext: str) -> str:
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
        "tif": "image/tiff", "tiff": "image/tiff",
        "pdf": "application/pdf",
        "csv": "text/csv", "txt": "text/plain", "md": "text/markdown",
        "json": "application/json", "tsv": "text/tab-separated-values",
        "html": "text/html", "htm": "text/html", "xml": "application/xml",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsm": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


def _gemini_extract(file_bytes: bytes, mime_type: str, filename: str, kind: str) -> tuple[str, float]:
    from google import genai as google_genai
    from google.genai import types as gtypes

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured (required for file reading)")

    prompt = _EXTRACT_PROMPT.format(filename=filename, kind=kind)
    parts = [
        gtypes.Part.from_text(text=prompt),
        gtypes.Part.from_bytes(data=file_bytes, mime_type=mime_type),
    ]

    client = google_genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=FILE_EXTRACTION_MODEL,
        contents=[gtypes.Content(role="user", parts=parts)],
        config=gtypes.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=65536,
        ),
    )
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("Gemini returned empty extraction")

    in_tok = out_tok = 0
    usage = getattr(resp, "usage_metadata", None)
    if usage:
        in_tok = getattr(usage, "prompt_token_count", 0) or 0
        out_tok = getattr(usage, "candidates_token_count", 0) or 0
    cost = calc_cost(FILE_EXTRACTION_MODEL, in_tok, out_tok)
    return text, cost


def _gemini_extract_text(raw: str, filename: str, kind: str) -> tuple[str, float]:
    """Text-only path: wrap content in the prompt (no binary part)."""
    from google import genai as google_genai
    from google.genai import types as gtypes

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured (required for file reading)")

    prompt = (
        _EXTRACT_PROMPT.format(filename=filename, kind=kind)
        + f"\n\n<file_content>\n{raw}\n</file_content>"
    )
    client = google_genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=FILE_EXTRACTION_MODEL,
        contents=[gtypes.Content(role="user", parts=[gtypes.Part.from_text(text=prompt)])],
        config=gtypes.GenerateContentConfig(temperature=0.2, max_output_tokens=65536),
    )
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("Gemini returned empty extraction")
    usage = getattr(resp, "usage_metadata", None)
    in_tok = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
    out_tok = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
    return text, calc_cost(FILE_EXTRACTION_MODEL, in_tok, out_tok)


def _excel_to_tsv(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                rows.append("\t".join(cells))
        if rows:
            parts.append(f"## Sheet: {sheet.title}\n" + "\n".join(rows))
    wb.close()
    if not parts:
        raise ValueError("No data found in spreadsheet")
    return "\n\n".join(parts)


def _max_bytes_for(ext: str) -> int:
    return _MAX_PDF_BYTES if ext == "pdf" else _MAX_INLINE_BYTES


def extract_file_bytes(data: bytes, filename: str) -> tuple[str, float]:
    """Extract readable content from file bytes via Gemini. Returns (text, cost_usd)."""
    name = filename or "attachment"
    ext = PurePath(name).suffix.lstrip(".").lower()
    limit = _max_bytes_for(ext)
    if len(data) > limit:
        mb = len(data) // (1024 * 1024)
        cap = limit // (1024 * 1024)
        raise ValueError(f"File too large ({mb} MB; max {cap} MB for .{ext or 'unknown'})")

    # Native multimodal: PDF, images, spreadsheets — one Gemini call with inline bytes.
    if ext == "pdf":
        text, cost = _gemini_extract(data, "application/pdf", name, "PDF")
        return text[:_MAX_OUTPUT_CHARS], cost

    if ext in _IMAGE_EXTS:
        text, cost = _gemini_extract(data, _mime_for_ext(ext), name, "image")
        return text[:_MAX_OUTPUT_CHARS], cost

    if ext in _EXCEL_EXTS:
        mime = _mime_for_ext(ext)
        try:
            text, cost = _gemini_extract(data, mime, name, "spreadsheet")
            return text[:_MAX_OUTPUT_CHARS], cost
        except Exception as exc:
            _log.info("Gemini native xlsx failed (%s), falling back to openpyxl+Gemini", exc)
            raw = _excel_to_tsv(data)
            text, cost = _gemini_extract_text(raw[:120_000], name, "spreadsheet")
            return text[:_MAX_OUTPUT_CHARS], cost

    if ext in _TEXT_EXTS or not ext:
        raw = data.decode("utf-8", errors="replace")
        if not raw.strip():
            raise ValueError("File is empty or not valid UTF-8 text")
        # Try native text mime first; fall back to text-in-prompt.
        try:
            text, cost = _gemini_extract(data, _mime_for_ext(ext) if ext else "text/plain", name, ext or "text")
            return text[:_MAX_OUTPUT_CHARS], cost
        except Exception:
            text, cost = _gemini_extract_text(raw[:120_000], name, ext or "text")
            return text[:_MAX_OUTPUT_CHARS], cost

    # Unknown: UTF-8 text or image magic bytes.
    try:
        raw = data.decode("utf-8")
        if raw.strip() and sum(1 for c in raw[:2000] if c.isprintable() or c in "\n\r\t") / max(len(raw[:2000]), 1) > 0.85:
            text, cost = _gemini_extract_text(raw[:120_000], name, ext or "unknown")
            return text[:_MAX_OUTPUT_CHARS], cost
    except UnicodeDecodeError:
        pass

    if data[:3] == b"\xff\xd8\xff":
        text, cost = _gemini_extract(data, "image/jpeg", name, "image")
        return text[:_MAX_OUTPUT_CHARS], cost
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        text, cost = _gemini_extract(data, "image/png", name, "image")
        return text[:_MAX_OUTPUT_CHARS], cost

    raise ValueError(f"Unsupported file type: .{ext or 'unknown'}")
