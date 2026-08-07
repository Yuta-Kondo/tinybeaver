import { useCallback, useEffect, useRef, useState } from "react";
import { UNDO_MS, useToast } from "../components/Toast";

/**
 * Destructive actions with a real undo.
 *
 * The API call is *deferred*, not fired-and-reversed: the row disappears
 * immediately, but nothing is sent until the undo window closes. Undo cancels
 * a delete that never happened, so there is no moment where the data is
 * actually gone and no restore endpoint to build.
 *
 * Returns `pending` — ids currently mid-undo-window, which the caller should
 * filter out of its list so the row vanishes the instant you click delete.
 */
export function useUndoableAction<T extends string | number>(opts: {
  /** Runs when the undo window closes without a cancel. */
  commit: (id: T) => Promise<void>;
  /** Message shown in the undo toast, e.g. `(n) => "Fact removed"`. */
  message: (id: T) => string;
  /** Called after a successful commit — usually a list reload. */
  onCommitted?: () => void;
  /** Called if the commit throws, so the caller can resync. */
  onFailed?: (id: T, err: unknown) => void;
}) {
  const { commit, message, onCommitted, onFailed } = opts;
  const toast = useToast();
  const [pending, setPending] = useState<Set<T>>(new Set());
  const timers = useRef(new Map<T, number>());

  // Anything still queued when the panel unmounts must not fire into a dead
  // component — but it also must not silently survive as a ghost delete.
  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((t) => window.clearTimeout(t));
      map.clear();
    };
  }, []);

  const cancel = useCallback((id: T) => {
    const t = timers.current.get(id);
    if (t != null) window.clearTimeout(t);
    timers.current.delete(id);
    setPending((p) => {
      const next = new Set(p);
      next.delete(id);
      return next;
    });
  }, []);

  const run = useCallback(
    (id: T) => {
      if (timers.current.has(id)) return;
      setPending((p) => new Set(p).add(id));

      const timer = window.setTimeout(async () => {
        timers.current.delete(id);
        try {
          await commit(id);
          onCommitted?.();
        } catch (err) {
          onFailed?.(id, err);
        } finally {
          setPending((p) => {
            const next = new Set(p);
            next.delete(id);
            return next;
          });
        }
      }, UNDO_MS);

      timers.current.set(id, timer);
      toast.show(message(id), "info", { label: "Undo", run: () => cancel(id) }, UNDO_MS);
    },
    [commit, message, onCommitted, onFailed, toast, cancel]
  );

  return { run, pending };
}
