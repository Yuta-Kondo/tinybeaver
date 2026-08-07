import { useEffect, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Keeps Tab inside an open overlay and returns focus where it came from.
 *
 * Without this, tabbing out of the command palette lands you in the chat
 * behind it — the dialog is visually modal but not modal to the keyboard,
 * which is the failure a screen-reader or keyboard-only user hits first.
 */
export function useFocusTrap(active: boolean, ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    // Focus the first control unless the overlay already placed focus itself
    // (the palette autofocuses its input, and stealing that would be worse).
    if (!container.contains(document.activeElement)) {
      container.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab" || !container) return;
      const items = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      );
      if (items.length === 0) return;

      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;

      if (e.shiftKey && (current === first || !container.contains(current))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && current === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Only restore if focus is still inside the closing overlay; otherwise
      // the user has already moved on and we would yank them back.
      if (!container || container.contains(document.activeElement)) {
        previouslyFocused?.focus?.();
      }
    };
  }, [active, ref]);
}
