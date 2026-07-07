import { useCallback, useRef, useState } from "react";
import { type AttachedFile, type GeoLocation, appendMessage, deleteMessage, editMessage, fetchSessionMessages, streamChat } from "../lib/api";
import { DEFAULT_MODEL } from "../lib/models";

export type MessageStatus = "searching" | "memory_updating" | "reading_email" | "moa_brainstorm" | "moa_synthesizing";

export interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  images?: string[];
  streaming?: boolean;
  status?: MessageStatus;
  newTopic?: string;
  loadedTopics?: string[];
  updatedTopics?: string[];
  fetchedUrls?: string[];
  model?: string;
  costUsd?: number;
  costBreakdown?: { chat: number; memory: number };
  locations?: GeoLocation[];
  searchSources?: { n: number; url: string; title: string }[];
  moaDrafts?: { persona: string; text: string; model?: string; done?: boolean }[];
  isError?: boolean;
  stopped?: boolean;
}

// Map raw error strings to a friendly, actionable message.
function friendlyError(raw: string): string {
  const s = (raw || "").toLowerCase();
  if (s.includes("429") || s.includes("resource_exhausted") || s.includes("quota") || s.includes("rate limit"))
    return "Rate limit reached for this model. Try again in a moment, or switch models.";
  if (s.includes("failed to fetch") || s.includes("networkerror") || s.includes("network"))
    return "Network error — check your connection and retry.";
  if (s.includes("overloaded") || s.includes("529"))
    return "The model is overloaded right now. Please retry.";
  if (s.includes("timeout") || s.includes("timed out"))
    return "The request timed out. Please retry.";
  return raw ? `Something went wrong: ${raw}` : "Something went wrong. Please retry.";
}

export function useChat(sessionId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);
  // Always-current mirror of messages + whether the active stream is private,
  // so cancel() can persist the partial reply without stale closures.
  const messagesRef = useRef<Message[]>([]);
  messagesRef.current = messages;
  const currentPrivateRef = useRef(false);
  // Remembers the last send so a failed turn can be retried verbatim.
  const lastSendRef = useRef<null | {
    text: string; onNewSession: (id: string) => void; images: string[];
    files: AttachedFile[]; model: string; multiAgent: boolean; privateMode: boolean;
  }>(null);
  // Tracks the active session for resend-after-edit
  const activeSessionRef = useRef<string | null>(sessionId);
  activeSessionRef.current = sessionId;

  const updateLastAssistant = (patch: Partial<Message>) => {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last?.role === "assistant") {
        copy[copy.length - 1] = { ...last, ...patch };
      }
      return copy;
    });
  };

  const _stream = useCallback(
    (text: string, sid: string | null, onNewSession: (id: string) => void, images: string[] = [], files: AttachedFile[] = [], model = DEFAULT_MODEL, multiAgent = false, privateMode = false, history: { role: string; content: string }[] = [], continueMessageId: number | null = null) => {
      currentPrivateRef.current = privateMode;
      const isContinue = continueMessageId != null;
      let resolvedSession = sid;
      let loadedTopics: string[] = [];

      cancelRef.current = streamChat(
        text,
        sid,
        (event) => {
          if (event.type === "start") {
            if (event.session_id && !resolvedSession) {
              resolvedSession = event.session_id;
              if (!privateMode) onNewSession(event.session_id);
            }
            loadedTopics = event.loaded_topics ?? [];
            if (isContinue) {
              // Resume the existing stopped bubble instead of adding a new one.
              updateLastAssistant({ streaming: true, stopped: false, status: undefined });
            } else {
              setMessages((prev) => {
                const copy = [...prev];
                // Attach the DB id to the user message we just sent, so its
                // assistant reply can offer "Regenerate" without a reload.
                if (event.user_message_id != null) {
                  for (let i = copy.length - 1; i >= 0; i--) {
                    if (copy[i].role === "user" && copy[i].id == null) {
                      copy[i] = { ...copy[i], id: event.user_message_id };
                      break;
                    }
                  }
                }
                copy.push({
                  role: "assistant",
                  content: "",
                  streaming: true,
                  newTopic: event.new_topic,
                  loadedTopics,
                  fetchedUrls: event.fetched_urls,
                });
                return copy;
              });
            }
          } else if (event.type === "searching") {
            updateLastAssistant({ status: "searching" });
          } else if (event.type === "reading_email") {
            updateLastAssistant({ status: "reading_email" });
          } else if (event.type === "moa_brainstorm") {
            updateLastAssistant({ status: "moa_brainstorm" });
          } else if (event.type === "moa_agent_start" && event.moa_persona) {
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") {
                const existing = last.moaDrafts ?? [];
                if (!existing.some((d) => d.persona === event.moa_persona)) {
                  copy[copy.length - 1] = {
                    ...last,
                    moaDrafts: [
                      ...existing,
                      {
                        persona: event.moa_persona!,
                        text: "",
                        model: event.moa_model ?? undefined,
                        done: false,
                      },
                    ],
                    status: "moa_brainstorm",
                  };
                }
              }
              return copy;
            });
          } else if (event.type === "moa_draft_delta" && event.moa_persona) {
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") {
                const existing = last.moaDrafts ?? [];
                const idx = existing.findIndex((d) => d.persona === event.moa_persona);
                const newDrafts = idx >= 0
                  ? existing.map((d, i) => i === idx ? {
                      ...d,
                      text: d.text + (event.moa_text ?? ""),
                      model: event.moa_model ?? d.model,
                    } : d)
                  : [...existing, {
                      persona: event.moa_persona!,
                      text: event.moa_text ?? "",
                      model: event.moa_model ?? undefined,
                      done: false,
                    }];
                copy[copy.length - 1] = { ...last, moaDrafts: newDrafts, status: "moa_brainstorm" };
              }
              return copy;
            });
          } else if (event.type === "moa_agent_done" && event.moa_persona) {
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") {
                const newDrafts = (last.moaDrafts ?? []).map((d) =>
                  d.persona === event.moa_persona
                    ? { ...d, done: true, model: event.moa_model ?? d.model }
                    : d
                );
                copy[copy.length - 1] = { ...last, moaDrafts: newDrafts };
              }
              return copy;
            });
          } else if (event.type === "moa_synthesizing") {
            updateLastAssistant({ status: "moa_synthesizing" });
          } else if (event.type === "delta" && event.text) {
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") {
                copy[copy.length - 1] = {
                  ...last,
                  content: last.content + event.text,
                  status: undefined,
                };
              }
              return copy;
            });
          } else if (event.type === "memory_updating") {
            updateLastAssistant({ status: "memory_updating" });
          } else if (event.type === "done") {
            updateLastAssistant({
              streaming: false,
              status: undefined,
              // Attach the DB id so actions (regenerate, feedback, delete) work
              // immediately, without needing a session reload.
              ...(event.message_id != null ? { id: event.message_id } : {}),
              updatedTopics: event.updated_topics ?? [],
              model: event.model,
              costUsd: event.cost_usd,
              costBreakdown: event.cost_breakdown,
              locations: event.locations,
              searchSources: event.search_sources,
              // moaDrafts preserved from earlier moa_draft events (don't overwrite)
            });
            setStreaming(false);
          } else if (event.type === "error") {
            const errMsg: Message = {
              role: "assistant",
              content: friendlyError(event.message ?? ""),
              streaming: false,
              isError: true,
            };
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              // Reuse the empty streaming bubble if present, else append.
              if (last?.role === "assistant" && last.streaming && !last.content) {
                copy[copy.length - 1] = errMsg;
              } else {
                copy.push(errMsg);
              }
              return copy;
            });
            setStreaming(false);
          }
        },
        images,
        files,
        model,
        multiAgent,
        privateMode,
        history,
        continueMessageId
      );
    },
    []
  );

  const sendMessage = useCallback(
    (text: string, onNewSession: (id: string) => void, images: string[] = [], files: AttachedFile[] = [], model = DEFAULT_MODEL, multiAgent = false, privateMode = false) => {
      if (streaming) return;
      lastSendRef.current = { text, onNewSession, images, files, model, multiAgent, privateMode };
      setMessages((prev) => [...prev, { role: "user", content: text, images }]);
      setStreaming(true);
      // In private mode, pass current messages as history so backend has context
      const history = privateMode
        ? messages.map((m) => ({ role: m.role, content: m.content })).filter((m) => m.content)
        : [];
      _stream(text, activeSessionRef.current, onNewSession, images, files, model, multiAgent, privateMode, history);
    },
    [streaming, _stream, messages]
  );

  // Retry after an error: drop the trailing error bubble (keep the user turn)
  // and replay the last send verbatim.
  const retryLast = useCallback(() => {
    const last = lastSendRef.current;
    if (streaming || !last) return;
    setMessages((prev) => {
      const copy = [...prev];
      if (copy[copy.length - 1]?.isError) copy.pop();
      return copy;
    });
    // History for private mode = everything before the failed user turn.
    const base = [...messages];
    if (base[base.length - 1]?.isError) base.pop();
    if (base[base.length - 1]?.role === "user") base.pop();
    const history = last.privateMode
      ? base.filter((m) => m.content && !m.isError).map((m) => ({ role: m.role, content: m.content }))
      : [];
    setStreaming(true);
    _stream(last.text, activeSessionRef.current, last.onNewSession, last.images, last.files, last.model, last.multiAgent, last.privateMode, history);
  }, [streaming, _stream, messages]);

  // Continue a stopped assistant reply — resumes streaming into the same bubble.
  const continueMessage = useCallback(
    (msgId: number) => {
      if (streaming || !activeSessionRef.current) return;
      const last = lastSendRef.current;
      setStreaming(true);
      _stream(
        "",
        activeSessionRef.current,
        () => {},
        [],
        [],
        last?.model ?? DEFAULT_MODEL,
        last?.multiAgent ?? false,
        last?.privateMode ?? false,
        [],
        msgId,
      );
    },
    [streaming, _stream],
  );

  const resendFromMessage = useCallback(
    async (
      msgId: number,
      newContent: string,
      onNewSession: (id: string) => void,
      model = DEFAULT_MODEL,
      multiAgent = false,
      privateMode = false,
    ) => {
      if (streaming || !activeSessionRef.current) return;
      await editMessage(activeSessionRef.current, msgId, newContent);
      const history = await fetchSessionMessages(activeSessionRef.current);
      setMessages(history.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        moaDrafts: m.moa_drafts,
        model: m.model ?? undefined,
        costUsd: m.cost_usd ?? undefined,
        costBreakdown: m.cost_breakdown ?? undefined,
      })));
      setStreaming(true);
      _stream(newContent, activeSessionRef.current, onNewSession, [], [], model, multiAgent, privateMode);
    },
    [streaming, _stream],
  );

  const deleteMessageFromSession = useCallback(async (msgId: number) => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    await deleteMessage(sid, msgId);
    setMessages((prev) => prev.filter((m) => m.id !== msgId));
  }, []);

  const cancel = useCallback(() => {
    cancelRef.current?.();
    setStreaming(false);
    const msgs = messagesRef.current;
    const last = msgs[msgs.length - 1];
    if (last?.role === "assistant" && last.streaming) {
      // Mark the partial reply as stopped and keep it visible.
      setMessages((prev) =>
        prev.map((m, i) =>
          i === prev.length - 1 && m.role === "assistant"
            ? { ...m, streaming: false, status: undefined, stopped: true }
            : m
        )
      );
      // Persist the partial so it survives a reload (skip private / already-saved / empty).
      const partial = last.content?.trim();
      const sid = activeSessionRef.current;
      if (!currentPrivateRef.current && sid && partial && last.id == null) {
        appendMessage(sid, "assistant", partial).then((id) => {
          if (id != null) {
            setMessages((prev) =>
              prev.map((m, i) => (i === prev.length - 1 ? { ...m, id } : m))
            );
          }
        });
      }
    }
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setStreaming(false);
  }, []);

  const loadSession = useCallback(async (id: string) => {
    setStreaming(false);
    setMessages([]);
    setLoadingSession(true);
    try {
      const history = await fetchSessionMessages(id);
      setMessages(history.map((m) => ({
        id: m.id, role: m.role, content: m.content, moaDrafts: m.moa_drafts,
        model: m.model ?? undefined,
        costUsd: m.cost_usd ?? undefined,
        costBreakdown: m.cost_breakdown ?? undefined,
      })));
    } finally {
      setLoadingSession(false);
    }
  }, []);

  return { messages, streaming, loadingSession, sendMessage, resendFromMessage, retryLast, continueMessage, cancel, clear, loadSession, deleteMessageFromSession };
}
