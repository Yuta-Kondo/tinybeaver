import { useCallback, useRef, useState } from "react";
import { type AttachedFile, type GeoLocation, editMessage, fetchSessionMessages, streamChat } from "../lib/api";

export type MessageStatus = "searching" | "memory_updating" | "reading_email";

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
}

export function useChat(sessionId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const cancelRef = useRef<(() => void) | null>(null);
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
    (text: string, sid: string | null, onNewSession: (id: string) => void, images: string[] = [], files: AttachedFile[] = []) => {
      let resolvedSession = sid;
      let loadedTopics: string[] = [];

      cancelRef.current = streamChat(
        text,
        sid,
        (event) => {
          if (event.type === "start") {
            if (event.session_id && !resolvedSession) {
              resolvedSession = event.session_id;
              onNewSession(event.session_id);
            }
            loadedTopics = event.loaded_topics ?? [];
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content: "",
                streaming: true,
                newTopic: event.new_topic,
                loadedTopics,
                fetchedUrls: event.fetched_urls,
              },
            ]);
          } else if (event.type === "searching") {
            updateLastAssistant({ status: "searching" });
          } else if (event.type === "reading_email") {
            updateLastAssistant({ status: "reading_email" });
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
              updatedTopics: event.updated_topics ?? [],
              model: event.model,
              costUsd: event.cost_usd,
              costBreakdown: event.cost_breakdown,
              locations: event.locations,
              searchSources: event.search_sources,
            });
            setStreaming(false);
          } else if (event.type === "error") {
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: `_Error: ${event.message}_`, streaming: false },
            ]);
            setStreaming(false);
          }
        },
        images,
        files
      );
    },
    []
  );

  const sendMessage = useCallback(
    (text: string, onNewSession: (id: string) => void, images: string[] = [], files: AttachedFile[] = []) => {
      if (streaming) return;
      setMessages((prev) => [...prev, { role: "user", content: text, images }]);
      setStreaming(true);
      _stream(text, activeSessionRef.current, onNewSession, images, files);
    },
    [streaming, _stream]
  );

  const resendFromMessage = useCallback(
    async (msgId: number, newContent: string, onNewSession: (id: string) => void) => {
      if (streaming || !activeSessionRef.current) return;
      // Edit in DB and truncate subsequent messages
      await editMessage(activeSessionRef.current, msgId, newContent);
      // Reload messages from DB to get the truncated state
      const history = await fetchSessionMessages(activeSessionRef.current);
      setMessages(history.map((m) => ({ id: m.id, role: m.role, content: m.content })));
      // Stream the new response
      setStreaming(true);
      _stream(newContent, activeSessionRef.current, onNewSession);
    },
    [streaming, _stream]
  );

  const cancel = useCallback(() => {
    cancelRef.current?.();
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setStreaming(false);
  }, []);

  const loadSession = useCallback(async (id: string) => {
    setStreaming(false);
    setMessages([]);
    const history = await fetchSessionMessages(id);
    setMessages(history.map((m) => ({ id: m.id, role: m.role, content: m.content })));
  }, []);

  return { messages, streaming, sendMessage, resendFromMessage, cancel, clear, loadSession };
}
