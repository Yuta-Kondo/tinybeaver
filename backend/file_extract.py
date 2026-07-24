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
import re
from collections.abc import Callable
from pathlib import PurePath

from .models import FILE_EXTRACTION_MODEL, calc_cost

_log = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "heic", "heif"})
_TEXT_EXTS = frozenset({"csv", "txt", "md", "json", "tsv", "log", "xml", "html", "htm"})
_EXCEL_EXTS = frozenset({"xlsx", "xlsm"})
# Google Gemini inline limits: PDFs 50 MB; other inline types up to 100 MB per request.
_MAX_PDF_BYTES = 50 * 1024 * 1024
_MAX_INLINE_BYTES = 100 * 1024 * 1024
# Soft cap only for non-PDF LLM extraction. PDF pages are OCR'd one-by-one with
# no global char cap so textbooks stay complete for retrieval.
_MAX_LLM_OUTPUT_CHARS = 200_000

_PAGE_OCR_PROMPT = """\
You are OCR-ing a single page of a PDF for a personal AI assistant that will later
search this text to answer questions (exercises, theorems, proofs).

Filename: {filename}
Page: {page} of {n_pages}

Rules:
- Output clean Markdown with ALL readable content: body text, headings, captions,
  footnotes, equations, exercise statements, and numbers.
- Preserve structure (headings, lists, numbered exercises like "Exercise 5.5").
- Math → LaTeX ($…$ / $$…$$) whenever possible.
- Tables → Markdown tables.
- Diagrams/figures → briefly describe and transcribe any labels/text in them.
- Do NOT summarize, skip exercises, or add commentary.
- Output ONLY the page content.
"""

# Pages with at least this much native text skip Flash OCR (textbooks with a
# real text layer). Sparse/scanned pages still get per-page Flash OCR.
_MIN_NATIVE_CHARS = 120
# Parallel Flash OCR workers for sparse pages (keep modest on small VPS).
_OCR_WORKERS = max(1, min(6, int(os.getenv("PDF_OCR_WORKERS", "4"))))
# Set PDF_OCR_ALL_PAGES=1 to force Flash on every page (slow/expensive).
_OCR_ALL_PAGES = os.getenv("PDF_OCR_ALL_PAGES", "").strip() in ("1", "true", "yes")


_EXTRACT_PROMPT = """\
You are extracting the full content of a file attachment for a personal AI assistant.

Filename: {filename}
Type: {kind}

Rules:
- Output clean Markdown preserving ALL meaningful content (text, numbers, tables, labels).
- Tables → Markdown tables with headers when possible.
- Images/diagrams → transcribe visible text (OCR) and briefly note non-text visuals.
- Spreadsheets → preserve every row and column; one section per sheet.
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


def _native_pdf_pages(data: bytes) -> tuple[list[str], int]:
    """Per-page native text via pypdf. Returns (pages_text_0indexed, page_count)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        pages.append(raw.strip())
    return pages, len(reader.pages)


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


def _gemini_ocr_page(
    page_pdf: bytes,
    filename: str,
    page: int,
    n_pages: int,
    client=None,
    retries: int = 3,
) -> tuple[str, float]:
    """OCR one PDF page with Gemini 3.5 Flash. Retries transient 503s."""
    import time
    from google import genai as google_genai
    from google.genai import types as gtypes

    if client is None:
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not configured (required for file reading)")
        client = google_genai.Client(api_key=api_key)

    prompt = _PAGE_OCR_PROMPT.format(filename=filename, page=page, n_pages=n_pages)
    parts = [
        gtypes.Part.from_text(text=prompt),
        gtypes.Part.from_bytes(data=page_pdf, mime_type="application/pdf"),
    ]
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=FILE_EXTRACTION_MODEL,
                contents=[gtypes.Content(role="user", parts=parts)],
                config=gtypes.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
            text = (resp.text or "").strip()
            in_tok = out_tok = 0
            usage = getattr(resp, "usage_metadata", None)
            if usage:
                in_tok = getattr(usage, "prompt_token_count", 0) or 0
                out_tok = getattr(usage, "candidates_token_count", 0) or 0
            return text, calc_cost(FILE_EXTRACTION_MODEL, in_tok, out_tok)
        except Exception as exc:
            last_err = exc
            msg = str(exc).lower()
            if attempt + 1 < retries and ("503" in msg or "unavailable" in msg or "high demand" in msg):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_err or RuntimeError("Gemini page OCR failed")


def _extract_pdf(
    data: bytes,
    filename: str,
    on_progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str, float]:
    """Extract a PDF fast: native text for rich pages, parallel Flash OCR for sparse ones.

    Set PDF_OCR_ALL_PAGES=1 to force Flash on every page (much slower).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    try:
        native_pages, n_pages = _native_pdf_pages(data)
    except Exception as exc:
        _log.warning("pypdf page count failed (%s)", exc)
        native_pages, n_pages = [], 0
        try:
            from pypdf import PdfReader
            n_pages = len(PdfReader(io.BytesIO(data)).pages)
            native_pages = [""] * n_pages
        except Exception:
            text, cost = _gemini_extract(data, "application/pdf", filename, "PDF")
            return text[:_MAX_LLM_OUTPUT_CHARS], cost

    if n_pages == 0:
        raise ValueError("PDF has no pages")
    if len(native_pages) < n_pages:
        native_pages = list(native_pages) + [""] * (n_pages - len(native_pages))

    if _cancelled():
        from .doc_store import IngestCancelled
        raise IngestCancelled()

    # Decide which pages need Flash OCR.
    ocr_indices: list[int] = []
    page_text: list[str | None] = [None] * n_pages
    for i, native in enumerate(native_pages):
        if _OCR_ALL_PAGES or len(native) < _MIN_NATIVE_CHARS:
            ocr_indices.append(i)
        else:
            page_text[i] = native

    _log.info(
        "Extracting %s: %d pages — %d native, %d Flash OCR (%s, workers=%d%s)",
        filename, n_pages, n_pages - len(ocr_indices), len(ocr_indices),
        FILE_EXTRACTION_MODEL, _OCR_WORKERS,
        ", ALL PAGES" if _OCR_ALL_PAGES else "",
    )
    if on_progress:
        on_progress(
            n_pages - len(ocr_indices),
            n_pages,
            f"Extracting… {n_pages - len(ocr_indices)}/{n_pages} pages native"
            + (f", {len(ocr_indices)} need OCR" if ocr_indices else ""),
        )

    total_cost = 0.0
    if ocr_indices:
        from google import genai as google_genai
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not configured (required for file reading)")
        client = google_genai.Client(api_key=api_key)

        def _one(i: int) -> tuple[int, str, float]:
            if _cancelled():
                from .doc_store import IngestCancelled
                raise IngestCancelled()
            page_no = i + 1
            try:
                page_pdf = _pdf_page_slice(data, i, i + 1)
                text, cost = _gemini_ocr_page(
                    page_pdf, filename, page_no, n_pages, client=client
                )
                if not text.strip() and native_pages[i]:
                    return i, native_pages[i], cost
                return i, text, cost
            except Exception as exc:
                from .doc_store import IngestCancelled
                if isinstance(exc, IngestCancelled):
                    raise
                _log.warning("OCR page %d/%d failed: %s", page_no, n_pages, exc)
                return i, native_pages[i], 0.0

        done_ocr = 0
        with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
            futures = {pool.submit(_one, i): i for i in ocr_indices}
            for fut in as_completed(futures):
                if _cancelled():
                    for f in futures:
                        f.cancel()
                    from .doc_store import IngestCancelled
                    raise IngestCancelled()
                i, text, cost = fut.result()
                page_text[i] = text
                total_cost += cost
                done_ocr += 1
                if on_progress and (done_ocr % 5 == 0 or done_ocr == len(ocr_indices)):
                    filled = sum(1 for t in page_text if t is not None)
                    on_progress(
                        filled, n_pages,
                        f"OCR {done_ocr}/{len(ocr_indices)} sparse pages "
                        f"({filled}/{n_pages} total)…",
                    )

    parts: list[str] = []
    for i, text in enumerate(page_text):
        body = (text or "").strip()
        if body:
            parts.append(f"## Page {i + 1}\n{body}")

    if on_progress:
        on_progress(n_pages, n_pages, f"Extracted {n_pages} pages")

    if not parts:
        raise ValueError("Could not extract text from PDF (all pages empty)")
    return "\n\n".join(parts), total_cost


def _max_bytes_for(ext: str) -> int:
    return _MAX_PDF_BYTES if ext == "pdf" else _MAX_INLINE_BYTES


def extract_file_bytes(
    data: bytes,
    filename: str,
    on_progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str, float]:
    """Extract readable content from file bytes. Returns (text, cost_usd).

    PDFs: native text for rich pages; parallel Gemini 3.5 Flash OCR for sparse
    pages (or every page if PDF_OCR_ALL_PAGES=1).
    """
    name = filename or "attachment"
    ext = PurePath(name).suffix.lstrip(".").lower()
    limit = _max_bytes_for(ext)
    if len(data) > limit:
        mb = len(data) // (1024 * 1024)
        cap = limit // (1024 * 1024)
        raise ValueError(f"File too large ({mb} MB; max {cap} MB for .{ext or 'unknown'})")

    if ext == "pdf":
        return _extract_pdf(data, name, on_progress=on_progress, should_cancel=should_cancel)

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
        return raw, 0.0

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
_PAGE_HDR = re.compile(r"^## Page (\d+)\b", re.MULTILINE)


def chunk_text(text: str, target: int = _CHUNK_TARGET, overlap: int = _CHUNK_OVERLAP) -> list[dict]:
    """Split text into overlapping passages with optional PDF page numbers.

    Returns list of ``{"text": str, "page": int | None}``.
    Page comes from ``## Page N`` markers written by PDF extract.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target:
        return [{"text": text, "page": _first_page(text)}]

    units = _split_units(text)
    raw: list[tuple[str, int | None]] = []
    buf = ""
    buf_page: int | None = None
    current_page: int | None = None

    for unit in units:
        page_in_unit = _first_page(unit)
        if page_in_unit is not None:
            current_page = page_in_unit
        unit_page = page_in_unit if page_in_unit is not None else current_page

        if not buf:
            buf = unit
            buf_page = unit_page
            continue
        if len(buf) + 1 + len(unit) <= target:
            buf = f"{buf}\n\n{unit}" if unit else buf
            if buf_page is None:
                buf_page = unit_page
            continue
        raw.append((buf.strip(), buf_page))
        tail = buf[-overlap:].lstrip() if overlap and len(buf) > overlap else ""
        buf = f"{tail}\n\n{unit}".strip() if tail else unit
        buf_page = unit_page

    if buf.strip():
        raw.append((buf.strip(), buf_page))

    out: list[dict] = []
    for c, page in raw:
        if len(c) <= target * 2:
            out.append({"text": c, "page": page if page is not None else _first_page(c)})
        else:
            for i in range(0, len(c), target - overlap):
                piece = c[i : i + target].strip()
                if piece:
                    out.append({
                        "text": piece,
                        "page": page if page is not None else _first_page(piece),
                    })
    return out


def _first_page(text: str) -> int | None:
    m = _PAGE_HDR.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _split_units(text: str) -> list[str]:
    """Break on ## headings / blank lines so chunks stay coherent."""
    # Split keeping page/heading markers attached to the following body.
    parts = re.split(r"\n(?=## )|\n{2,}", text)
    return [p.strip() for p in parts if p and p.strip()]
