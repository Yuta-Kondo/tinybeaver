import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";

export type ToastTone = "error" | "success" | "info";

type Toast = {
  id: number;
  tone: ToastTone;
  message: string;
  /** Optional single action, e.g. "Retry". Dismisses the toast when run. */
  action?: { label: string; run: () => void };
};

type ToastApi = {
  show: (message: string, tone?: ToastTone, action?: Toast["action"], duration?: number) => void;
  error: (message: string, action?: Toast["action"]) => void;
  success: (message: string) => void;
};

/** How long an undoable action stays reversible. The deferred work and the
 *  toast offering to cancel it MUST share this number, or the button outlives
 *  the window in which it does anything.
 *
 *  10s rather than the usual 6: what's being undone here is a memory fact,
 *  which you may want back only after reading the toast and thinking about
 *  it — and 6s isn't enough time to do both. */
export const UNDO_MS = 10000;

const ToastContext = createContext<ToastApi | null>(null);

/** How long each tone stays up. Errors linger — you may need to read them. */
const TTL: Record<ToastTone, number> = {
  error: 7000,
  success: 3000,
  info: 4500,
};

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const show = useCallback(
    (message: string, tone: ToastTone = "info", action?: Toast["action"], duration?: number) => {
      const id = nextId++;
      setToasts((t) => [...t.slice(-2), { id, tone, message, action }]);
      window.setTimeout(() => dismiss(id), duration ?? TTL[tone]);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      error: (m, action) => show(m, "error", action),
      success: (m) => show(m, "success"),
    }),
    [show]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast toast--${t.tone}`}>
              <span className="toast-message">{t.message}</span>
              {t.action && (
                <button
                  className="toast-action"
                  onClick={() => {
                    t.action!.run();
                    dismiss(t.id);
                  }}
                >
                  {t.action.label}
                </button>
              )}
              <button
                className="toast-close"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
              >
                <Icon name="close" size={12} />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}

/** Toasts are optional: components outside the provider get a no-op that
 *  falls back to the console, so a missing provider can't crash a render. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  return (
    ctx ?? {
      show: (m) => console.warn("[toast]", m),
      error: (m) => console.error("[toast]", m),
      success: (m) => console.info("[toast]", m),
    }
  );
}
