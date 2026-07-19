import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./Icon";

interface Props {
  /** Only selections inside this element show the toolbar. */
  containerRef: React.RefObject<HTMLElement | null>;
}

interface Pos {
  top: number;
  left: number;
}

/** Nearest KaTeX wrapper containing a node, if any. */
function closestKatex(node: Node | null): Element | null {
  if (!node) return null;
  const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as Element);
  return el?.closest?.(".katex") ?? null;
}

/**
 * Grow a range so it fully encloses any KaTeX element its endpoints land
 * inside. Selecting just the rendered formula puts both endpoints *within*
 * the .katex node, so cloneContents() would otherwise miss the LaTeX source.
 */
function expandRangeToMath(range: Range): Range {
  const r = range.cloneRange();
  const startKatex = closestKatex(r.startContainer);
  if (startKatex) r.setStartBefore(startKatex);
  const endKatex = closestKatex(r.endContainer);
  if (endKatex) r.setEndAfter(endKatex);
  return r;
}

/**
 * Reconstruct the plain text of a selection Range, replacing rendered KaTeX
 * with its raw LaTeX source ($…$ inline, $$…$$ display) so copied math pastes
 * back as editable LaTeX rather than garbled glyphs.
 */
export function extractSelectionText(range: Range): string {
  const holder = document.createElement("div");
  holder.appendChild(expandRangeToMath(range).cloneContents());

  // Display math first — replace the whole .katex-display wrapper.
  holder.querySelectorAll(".katex-display").forEach((disp) => {
    const tex = disp
      .querySelector('annotation[encoding="application/x-tex"]')
      ?.textContent?.trim();
    disp.replaceWith(document.createTextNode(tex ? `$$${tex}$$` : ""));
  });

  // Remaining inline math.
  holder.querySelectorAll(".katex").forEach((node) => {
    const tex = node
      .querySelector('annotation[encoding="application/x-tex"]')
      ?.textContent?.trim();
    node.replaceWith(document.createTextNode(tex ? `$${tex}$` : ""));
  });

  // Read with block-level line breaks preserved via innerText (needs layout).
  holder.style.position = "fixed";
  holder.style.left = "-9999px";
  holder.style.top = "0";
  document.body.appendChild(holder);
  const text = holder.innerText;
  document.body.removeChild(holder);

  return text.replace(/\n{3,}/g, "\n\n").trim();
}

const TOOLBAR_W = 92;
const TOOLBAR_H = 34;

export default function SelectionToolbar({ containerRef }: Props) {
  const [pos, setPos] = useState<Pos | null>(null);
  const [copied, setCopied] = useState(false);
  const rangeRef = useRef<Range | null>(null);
  const copiedTimer = useRef<number | null>(null);

  const hide = useCallback(() => {
    setPos(null);
    setCopied(false);
    rangeRef.current = null;
  }, []);

  const evaluate = useCallback(() => {
    const sel = window.getSelection();
    const container = containerRef.current;
    if (!sel || sel.isCollapsed || sel.rangeCount === 0 || !container) {
      hide();
      return;
    }
    const range = sel.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) {
      hide();
      return;
    }
    if (!sel.toString().trim()) {
      hide();
      return;
    }

    const rect = range.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
      hide();
      return;
    }
    rangeRef.current = range.cloneRange();

    const left = Math.min(
      Math.max(8, rect.left + rect.width / 2 - TOOLBAR_W / 2),
      window.innerWidth - TOOLBAR_W - 8
    );
    const top =
      rect.top - TOOLBAR_H - 8 < 8
        ? rect.bottom + 8
        : rect.top - TOOLBAR_H - 8;
    setPos({ top, left });
    setCopied(false);
  }, [containerRef, hide]);

  useEffect(() => {
    const onMouseUp = () => window.setTimeout(evaluate, 0);
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.shiftKey || e.key === "Shift") window.setTimeout(evaluate, 0);
    };
    const onSelectionChange = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) hide();
    };
    document.addEventListener("mouseup", onMouseUp);
    document.addEventListener("touchend", onMouseUp);
    document.addEventListener("keyup", onKeyUp);
    document.addEventListener("selectionchange", onSelectionChange);
    return () => {
      document.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("touchend", onMouseUp);
      document.removeEventListener("keyup", onKeyUp);
      document.removeEventListener("selectionchange", onSelectionChange);
    };
  }, [evaluate, hide]);

  // Reposition/hide on scroll or resize so the toolbar never floats orphaned.
  useEffect(() => {
    if (!pos) return;
    const reposition = () => evaluate();
    window.addEventListener("resize", reposition);
    const container = containerRef.current;
    container?.addEventListener("scroll", reposition, { passive: true });
    return () => {
      window.removeEventListener("resize", reposition);
      container?.removeEventListener("scroll", reposition);
    };
  }, [pos, evaluate, containerRef]);

  useEffect(
    () => () => {
      if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    },
    []
  );

  const copy = useCallback(() => {
    const range = rangeRef.current;
    if (!range) return;
    const text = extractSelectionText(range);
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
      copiedTimer.current = window.setTimeout(hide, 1200);
    });
  }, [hide]);

  if (!pos) return null;

  return (
    <div
      className="selection-toolbar"
      style={{ top: pos.top, left: pos.left }}
      role="toolbar"
      onMouseDown={(e) => e.preventDefault()}
    >
      <button className="selection-toolbar-btn" onClick={copy} title="Copy selection">
        <Icon name={copied ? "check" : "copy"} size={13} />
        <span>{copied ? "Copied" : "Copy"}</span>
      </button>
    </div>
  );
}
