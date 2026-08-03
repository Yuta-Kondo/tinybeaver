/**
 * In-app help: keyboard shortcuts + model data residency / training notes.
 * Keep summaries short; full research lives in docs/provider-data-pricing-notes.md.
 */

import { MODELS, type ModelOption } from "./models";

const isMac =
  typeof navigator !== "undefined" &&
  /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent);

export const MOD = isMac ? "⌘" : "Ctrl";
export const MOD_SHIFT = isMac ? "⌘⇧" : "Ctrl+Shift+";

export interface ShortcutRow {
  keys: string;
  label: string;
}

export const SHORTCUTS: ShortcutRow[] = [
  { keys: `${MOD_SHIFT}O`, label: "New chat" },
  { keys: `${MOD}K`, label: "Command palette" },
  { keys: "Any letter", label: "Focus chat input (when not typing elsewhere)" },
  { keys: "Esc", label: "Close palette / help / cancel edit" },
];

export type PrivacyTrain = "no" | "paid-no" | "unclear" | "yes-free";

export interface ProviderPrivacy {
  id: ModelOption["provider"];
  name: string;
  hq: string;
  dataLocation: string;
  training: string;
  trainKind: PrivacyTrain;
  note: string;
}

/** Per-provider privacy summary shown in Help → Models & data. */
export const PROVIDER_PRIVACY: ProviderPrivacy[] = [
  {
    id: "anthropic",
    name: "Anthropic (Claude)",
    hq: "United States",
    dataLocation: "US / global inference (not China). Workspace storage is typically US-centric.",
    training: "Commercial API: not used for training by default (unless you opt in / send feedback).",
    trainKind: "no",
    note: "Best default for personal memory and email context.",
  },
  {
    id: "gemini",
    name: "Google (Gemini)",
    hq: "United States",
    dataLocation: "Google global infrastructure (Developer API). Not PRC-hosted; not region-pinned like Vertex unless you configure that.",
    training: "Paid / billing-enabled project: not used to improve Google products. Free / unpaid quota: may be used to improve products.",
    trainKind: "paid-no",
    note: "Confirm your GOOGLE_API_KEY project shows Paid on the Gemini API key page.",
  },
  {
    id: "glm",
    name: "Z.ai (GLM)",
    hq: "Singapore entity; Zhipu AI group (China)",
    dataLocation: "Z.ai states API processing is generally in Singapore. Corporate group remains PRC-linked (jurisdiction residual risk).",
    training: "API DPA claims: content processed in real time, not stored on their servers, not used for training.",
    trainKind: "no",
    note: "Used for Self-MoA and optional chat. Different from DeepSeek’s explicit “stored in China” policy.",
  },
];

export function modelsForProvider(provider: ModelOption["provider"]): ModelOption[] {
  return MODELS.filter((m) => m.provider === provider);
}

export function trainBadge(kind: PrivacyTrain): { label: string; tone: "ok" | "warn" | "bad" | "muted" } {
  switch (kind) {
    case "no":
      return { label: "No train (default)", tone: "ok" };
    case "paid-no":
      return { label: "No train if paid", tone: "warn" };
    case "yes-free":
      return { label: "May train (free)", tone: "bad" };
    default:
      return { label: "Unclear", tone: "muted" };
  }
}
