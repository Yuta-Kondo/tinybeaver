/**
 * Model registry — the single source of truth for the frontend.
 *
 * To add a model: add one entry here AND one in backend/models.py (the `MODELS`
 * dict). Everything else (dropdown, command palette, validation, labels) reads
 * from this array, so no other file needs to change.
 */

export interface ModelOption {
  id: string;
  name: string;
  version: string;
  provider: "anthropic" | "gemini" | "glm";
  desc: string;
}

export const MODELS: ModelOption[] = [
  { id: "claude-haiku-4-5-20251001", name: "Haiku",  version: "4.5", provider: "anthropic", desc: "Fast & efficient" },
  { id: "claude-sonnet-4-6",         name: "Sonnet", version: "4.6", provider: "anthropic", desc: "Balanced" },
  { id: "claude-sonnet-5",           name: "Sonnet", version: "5",   provider: "anthropic", desc: "Recommended" },
  { id: "claude-opus-4-8",           name: "Opus",   version: "4.8", provider: "anthropic", desc: "Most capable" },
  { id: "gemini-3.5-flash",          name: "Flash",  version: "3.5", provider: "gemini",    desc: "Google · Fast" },
  { id: "glm-5.2",                   name: "GLM",    version: "5.2", provider: "glm",       desc: "Zhipu · Open weight" },
];

/** Default model — must match backend `DEFAULT_MODEL`. */
export const DEFAULT_MODEL = "claude-sonnet-5";

/** MoA pipeline — keep in sync with backend/models.py MOA_* */
export const MOA_SYNTHESIS_MODEL = "claude-sonnet-5";

export const MOA_AGENTS = [
  { persona: "Advocate", model: "gemini-3.5-flash" },
  { persona: "Skeptic", model: "glm-5.2" },
  { persona: "Minimalist", model: "claude-haiku-4-5-20251001" },
] as const;

/** Short display name, e.g. "Flash 3.5" or "Sonnet 5". */
export function modelShortLabel(id: string): string {
  const opt = MODELS.find((m) => m.id === id);
  if (opt) return `${opt.name} ${opt.version}`;
  return modelLabel(id);
}

/** One-line summary of the full MoA pipeline for tooltips. */
export function moaPipelineLabel(): string {
  const agents = MOA_AGENTS.map((a) => modelShortLabel(a.model)).join(" · ");
  return `${agents} → ${modelShortLabel(MOA_SYNTHESIS_MODEL)}`;
}

/** Model id for a MoA persona (falls back to empty string). */
export function moaAgentModel(persona: string): string {
  return MOA_AGENTS.find((a) => a.persona === persona)?.model ?? "";
}

/** Quick allow-list derived from MODELS (replaces inline arrays). */
export const ALLOWED_MODELS: string[] = MODELS.map((m) => m.id);

/** True if `id` is a selectable model. */
export function isAllowedModel(id: string | null | undefined): boolean {
  return !!id && ALLOWED_MODELS.includes(id);
}

/** Resolve a stored/localStorage model id to a valid one (falls back to default). */
export function resolveModel(id: string | null | undefined): string {
  return isAllowedModel(id) ? (id as string) : DEFAULT_MODEL;
}

/** Find the ModelOption for an id (falls back to the default entry). */
export function findModel(id: string): ModelOption {
  return MODELS.find((m) => m.id === id) ?? MODELS[2];
}

/**
 * Short display label for a model id, used in the message metadata row.
 * Handles special "moa" label plus the standard models.
 */
export function modelLabel(id: string): string {
  if (id === "moa") return "Multi";
  const opt = MODELS.find((m) => m.id === id);
  if (opt) return opt.name;
  // Backwards-compatible fallback for ids not in the registry.
  if (id.includes("opus")) return "Opus";
  if (id.includes("sonnet")) return "Sonnet";
  if (id.includes("haiku")) return "Haiku";
  if (id.includes("fable")) return "Fable";
  if (id.includes("flash")) return "Flash";
  return id;
}