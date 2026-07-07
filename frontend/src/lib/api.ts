import { DEFAULT_MODEL } from "./models";

export interface SessionInfo {
  session_id: string;
  title: string;
  message_count: number;
}

export interface SessionSearchResult {
  session_id: string;
  title: string;
  snippet: string;
}

export interface GeoLocation {
  name: string;
  query: string;
  // legacy fields kept for compatibility
  address?: string;
  lat?: number;
  lng?: number;
  display_name?: string;
}

export interface StreamEvent {
  type: "start" | "delta" | "done" | "error" | "searching" | "memory_updating" | "reading_email" | "moa_brainstorm" | "moa_synthesizing" | "moa_draft" | "moa_draft_delta" | "moa_agent_start" | "moa_agent_done";
  session_id?: string;
  message_id?: number | null;
  user_message_id?: number | null;
  text?: string;
  message?: string;
  new_topic?: string;
  loaded_topics?: string[];
  updated_topics?: string[];
  fetched_urls?: string[];
  model?: string;
  cost_usd?: number;
  cost_breakdown?: { chat: number; memory: number };
  locations?: GeoLocation[];
  search_sources?: { n: number; url: string; title: string }[];
  moa_persona?: string;
  moa_model?: string;
  moa_text?: string;
}

export interface TopicSummary {
  slug: string;
  description: string;
}

export interface TopicDetail {
  slug: string;
  description: string;
  content: string;
  updated_at: string;
}

export interface SearchResult {
  slug: string;
  snippet: string;
}

export interface SemanticResult {
  slug: string;
  score: number;
}

export interface Task {
  id: string;
  title: string;
  prompt: string;
  schedule: string;
  schedule_label: string;
  next_run: string | null;
  active: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function fetchSessions(): Promise<SessionInfo[]> {
  const r = await fetch("/sessions");
  if (!r.ok) throw new Error("Failed to fetch sessions");
  return r.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`/sessions/${id}`, { method: "DELETE" });
}

export async function appendMessage(id: string, role: "assistant" | "user", content: string): Promise<number | null> {
  try {
    const r = await fetch(`/sessions/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, content }),
    });
    if (!r.ok) return null;
    const data = await r.json();
    return data.id ?? null;
  } catch {
    return null;
  }
}

export async function renameSession(id: string, title: string): Promise<void> {
  const r = await fetch(`/sessions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("Failed to rename session");
}

export async function sendFeedback(
  rating: "up" | "down",
  message: string,
  note = ""
): Promise<void> {
  await fetch("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, message, note }),
  });
}

export async function searchSessions(q: string): Promise<SessionSearchResult[]> {
  const r = await fetch(`/sessions/search?q=${encodeURIComponent(q)}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.results;
}

export async function fetchSessionMessages(
  id: string
): Promise<Array<{ id: number; role: "user" | "assistant"; content: string; moa_drafts?: { persona: string; text: string; model?: string; done?: boolean }[]; model?: string | null; cost_usd?: number | null; cost_breakdown?: { chat: number; memory: number } | null }>> {
  const r = await fetch(`/sessions/${id}/messages`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.messages;
}

export async function editMessage(sessionId: string, msgId: number, content: string): Promise<void> {
  const r = await fetch(`/sessions/${sessionId}/messages/${msgId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!r.ok) throw new Error("Failed to edit message");
}

export async function deleteMessage(sessionId: string, msgId: number): Promise<void> {
  const r = await fetch(`/sessions/${sessionId}/messages/${msgId}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Failed to delete message");
}

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------

export async function fetchTopics(): Promise<TopicSummary[]> {
  const r = await fetch("/topics");
  if (!r.ok) throw new Error("Failed to fetch topics");
  const data = await r.json();
  return data.topics;
}

export async function fetchTopic(slug: string): Promise<TopicDetail> {
  const r = await fetch(`/topics/${encodeURIComponent(slug)}`);
  if (!r.ok) throw new Error("Topic not found");
  return r.json();
}

export async function saveTopic(slug: string, content: string, description = ""): Promise<void> {
  const r = await fetch(`/topics/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, description }),
  });
  if (!r.ok) throw new Error("Failed to save topic");
}

export async function createTopic(slug: string, description = ""): Promise<void> {
  const r = await fetch(`/topics/${encodeURIComponent(slug)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: "Failed to create topic" }));
    throw new Error(err.detail ?? "Failed to create topic");
  }
}

export async function searchTopics(q: string): Promise<SearchResult[]> {
  const r = await fetch(`/topics/search?q=${encodeURIComponent(q)}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.results;
}

export async function semanticSearchTopics(q: string): Promise<SemanticResult[]> {
  const r = await fetch(`/topics/semantic-search?q=${encodeURIComponent(q)}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.results ?? [];
}

export async function deleteTopic(slug: string): Promise<void> {
  const r = await fetch(`/topics/${encodeURIComponent(slug)}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Failed to delete topic");
}

export async function reindexTopics(): Promise<number> {
  const r = await fetch("/topics/reindex", { method: "POST" });
  if (!r.ok) throw new Error("Reindex failed");
  const data = await r.json();
  return data.updated ?? 0;
}

export async function reflect(): Promise<string[]> {
  const r = await fetch("/reflect", { method: "POST" });
  if (!r.ok) throw new Error("Reflect failed");
  const data = await r.json();
  return data.updated;
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

export async function extractFile(file: File): Promise<{ filename: string; text: string; chars: number; size_kb: number; cost_usd: number }> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch("/files/extract", { method: "POST", body: form });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: "Failed to extract file" }));
    throw new Error(err.detail ?? "Failed to extract file");
  }
  return r.json();
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export async function fetchTasks(): Promise<Task[]> {
  const r = await fetch("/tasks");
  if (!r.ok) throw new Error("Failed to fetch tasks");
  const data = await r.json();
  return data.tasks;
}

export async function createTask(title: string, prompt: string, schedule: string): Promise<{ id: string; next_run: string | null }> {
  const r = await fetch("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, prompt, schedule }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: "Failed to create task" }));
    throw new Error(err.detail ?? "Failed to create task");
  }
  return r.json();
}

export async function toggleTask(id: string, active: boolean): Promise<void> {
  await fetch(`/tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
  });
}

export async function deleteTask(id: string): Promise<void> {
  await fetch(`/tasks/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Gmail
// ---------------------------------------------------------------------------

export interface EmailSummary {
  id: string;
  from: string;
  subject: string;
  date: string;
  snippet: string;
}

export interface EmailDetail extends EmailSummary {
  to: string;
  body: string;
}

export async function gmailStatus(): Promise<{ connected: boolean; email?: string }> {
  const r = await fetch("/auth/gmail/status");
  return r.json();
}

export async function gmailStartAuth(): Promise<string> {
  const r = await fetch("/auth/gmail/start");
  const data = await r.json();
  return data.url as string;
}

export async function gmailDisconnect(): Promise<void> {
  await fetch("/auth/gmail/disconnect", { method: "DELETE" });
}

export async function fetchEmails(q = "", max_results = 20): Promise<EmailSummary[]> {
  const params = new URLSearchParams({ q, max_results: String(max_results) });
  const r = await fetch(`/emails?${params}`);
  if (!r.ok) throw new Error("Failed to fetch emails");
  const data = await r.json();
  return data.emails;
}

export async function fetchEmail(id: string): Promise<EmailDetail> {
  const r = await fetch(`/emails/${id}`);
  if (!r.ok) throw new Error("Failed to fetch email");
  return r.json();
}

// ---------------------------------------------------------------------------
// Chat stream
// ---------------------------------------------------------------------------

export interface AttachedFile {
  name: string;
  text: string;
}

export function streamChat(
  message: string,
  sessionId: string | null,
  onEvent: (e: StreamEvent) => void,
  images: string[] = [],
  files: AttachedFile[] = [],
  model = DEFAULT_MODEL,
  multiAgent = false,
  privateMode = false,
  history: { role: string; content: string }[] = [],
  continueMessageId: number | null = null
): () => void {
  const controller = new AbortController();

  (async () => {
    const resp = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId, images, files, model, multi_agent: multiAgent, private: privateMode, history, continue_message_id: continueMessageId }),
      signal: controller.signal,
    });

    if (!resp.body) return;
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split("\n");
      buf = lines.pop()!;

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch {
          // ignore malformed
        }
      }
    }
  })().catch((e) => {
    if (e?.name !== "AbortError") {
      onEvent({ type: "error", message: String(e) });
    }
  });

  return () => controller.abort();
}
