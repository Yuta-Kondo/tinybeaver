import { useEffect } from "react";

/**
 * Closes an overlay on Escape.
 *
 * Registered in the capture phase so it fires before anything inside the
 * overlay swallows the key, and only while `active` — otherwise every closed
 * overlay on the page would still be listening.
 */
export function useEscapeKey(active: boolean, onClose: () => void) {
  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      onClose();
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [active, onClose]);
}
