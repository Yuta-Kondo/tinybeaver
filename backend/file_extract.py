"""File extraction for session documents.

Strategy (NotebookLM-style ingest):
- Text-based PDFs → native text via pypdf (complete, cheap, no LLM truncation).
- Scanned/image PDFs → Gemini multimodal in page-range batches.
- Images / spreadsheets / plain text → same as before (Gemini or decode).

Full extracted text is returned untruncated so the caller can chunk + embed it.
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
# Soft cap only for the LLM-extraction path (Gemini can't dump unlimited output).
# Native PDF text has no cap — textbooks stay whole and are retrieved by chunk.
_MAX_LLM_OUTPUT_CHARS = 200_000
# If native PDF yields fewer than this many chars per page on average, treat as scanned.
_MIN_CHARS_PER_PAGE = 40
# Gemini page-batch size for scanned PDFs.
_SCANNED_PAGES_PER_BATCH = 8

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


def _native_pdf_text(data: bytes) -> tuple[str, int]:
    """Extract text from a PDF with pypdf. Returns (text, page_count)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        text = raw.strip()
        if text:
            pages.append(f"## Page {i}\n{text}")
    return "\n\n".join(pages), len(reader.pages)


def _pdf_page_slice(data: bytes, start: int, end: int) -> bytes:
    """Return a new PDF containing pages [start, end) (0-indexed)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _extract_pdf(data: bytes, filename: str) -> tuple[str, float]:
    """Native text first; Gemini OCR in page batches if the PDF looks scanned."""
    try:
        native, n_pages = _native_pdf_text(data)
    except Exception as exc:
        _log.info("pypdf failed (%s); falling back to Gemini for whole PDF", exc)
        text, cost = _gemini_extract(data, "application/pdf", filename, "PDF")
        return text[:_MAX_LLM_OUTPUT_CHARS], cost

    avg = (len(native) / n_pages) if n_pages else 0
    if native.strip() and avg >= _MIN_CHARS_PER_PAGE:
        # Text-based PDF — keep the full native extract (no LLM truncation).
        return native, 0.0

    # Scanned / image-heavy: OCR via Gemini in page-range batches so a textbook
    # isn't crushed into a single truncated dump.
    _log.info(
        "PDF %s looks scanned (avg %.0f chars/page across %d pages) — Gemini OCR batches",
        filename, avg, n_pages,
    )
    if n_pages == 0:
        text, cost = _gemini_extract(data, "application/pdf", filename, "PDF")
        return text[:_MAX_LLM_OUTPUT_CHARS], cost

    parts: list[str] = []
    total_cost = 0.0
    for start in range(0, n_pages, _SCANNED_PAGES_PER_BATCH):
        end = min(start + _SCANNED_PAGES_PER_BATCH, n_pages)
        slice_bytes = _pdf_page_slice(data, start, end)
        kind = f"PDF pages {start + 1}–{end} of {n_pages}"
        try:
            text, cost = _gemini_extract(slice_bytes, "application/pdf", filename, kind)
        except Exception as exc:
            _log.warning("Gemini OCR batch %d–%d failed: %s", start + 1, end, exc)
            continue
        total_cost += cost
        if text.strip():
            parts.append(f"## Pages {start + 1}–{end}\n{text.strip()}")

    if not parts and native.strip():
        # OCR failed entirely — keep whatever native text we got.
        return native, total_cost
    if not parts:
        raise ValueError("Could not extract text from PDF (scanned pages returned empty)")
    return "\n\n".join(parts), total_cost


def _max_bytes_for(ext: str) -> int:
    return _MAX_PDF_BYTES if ext == "pdf" else _MAX_INLINE_BYTES


def extract_file_bytes(data: bytes, filename: str) -> tuple[str, float]:
    """Extract readable content from file bytes. Returns (text, cost_usd).

    For text PDFs the returned string is the full native extract (no char cap).
    LLM paths are soft-capped so a single Gemini call can't blow memory.
    """
    name = filename or "attachment"
    ext = PurePath(name).suffix.lstrip(".").lower()
    limit = _max_bytes_for(ext)
    if len(data) > limit:
        mb = len(data) // (1024 * 1024)
        cap = limit // (1024 * 1024)
        raise ValueError(f"File too large ({mb} MB; max {cap} MB for .{ext or 'unknown'})")

    if ext == "pdf":
        return _extract_pdf(data, name)

    if ext in _IMAGE_EXTS:
        text, cost = _gemini_extract(data, _mime_for_ext(ext), name, "image")
        return text[:_MAX_LLM_OUTPUT_CHARS], cost

    if ext in _EXCEL_EXTS:
        mime = _mime_for_ext(ext)
        try:
            text, cost = _gemini_extract(data, mime, name, "spreadsheet")
            return text[:_MAX_LLM_OUTPUT_CHARS], cost
        except Exception as exc:
            _log.info("Gemini native xlsx failed (%s), falling back to openpyxl+Gemini", exc)
            raw = _excel_to_tsv(data)
            text, cost = _gemini_extract_text(raw[:200_000], name, "spreadsheet")
            return text[:_MAX_LLM_OUTPUT_CHARS], cost

    if ext in _TEXT_EXTS or not ext:
        raw = data.decode("utf-8", errors="replace")
        if not raw.strip():
            raise ValueError("File is empty or not valid UTF-8 text")
        # Plain text files: keep the raw content (no LLM rewrite / truncation).
        return raw, 0.0

    # Unknown: UTF-8 text or image magic bytes.
    try:
        raw = data.decode("utf-8")
        if raw.strip() and sum(1 for c in raw[:2000] if c.isprintable() or c in "\n\r\t") / max(len(raw[:2000]), 1) > 0.85:
            return raw, 0.0
    except UnicodeDecodeError:
        pass

    if data[:3] == b"\xff\xd8\xff":
        text, cost = _gemini_extract(data, "image/jpeg", name, "image")
        return text[:_MAX_LLM_OUTPUT_CHARS], cost
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        text, cost = _gemini_extract(data, "image/png", name, "image")
        return text[:_MAX_LLM_OUTPUT_CHARS], cost

    raise ValueError(f"Unsupported file type: .{ext or 'unknown'}")


# ---------------------------------------------------------------------------
# Chunking — used after extract so large docs are retrieved, not dumped
# ---------------------------------------------------------------------------

_CHUNK_TARGET = 1_200   # ~chars per passage
_CHUNK_OVERLAP = 150


def chunk_text(text: str, target: int = _CHUNK_TARGET, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping passages, preferring paragraph / page breaks."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target:
        return [text]

    # Prefer splitting on page/heading markers or blank lines.
    units = _split_units(text)
    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
            continue
        if len(buf) + 1 + len(unit) <= target:
            buf = f"{buf}\n\n{unit}" if unit else buf
            continue
        chunks.append(buf.strip())
        # Overlap: keep the tail of the previous chunk.
        tail = buf[-overlap:].lstrip() if overlap and len(buf) > overlap else ""
        buf = f"{tail}\n\n{unit}".strip() if tail else unit
    if buf.strip():
        chunks.append(buf.strip())

    # Hard-split any leftover mega-unit that refused to break.
    out: list[str] = []
    for c in chunks:
        if len(c) <= target * 2:
            out.append(c)
        else:
            for i in range(0, len(c), target - overlap):
                piece = c[i:i + target].strip()
                if piece:
                    out.append(piece)
    return out


def _split_units(text: str) -> list[str]:
    """Break on ## headings / blank lines so chunks stay coherent."""
    import re
    # Split keeping page/heading markers attached to the following body.
    parts = re.split(r"\n(?=## )|\n{2,}", text)
    return [p.strip() for p in parts if p and p.strip()]
