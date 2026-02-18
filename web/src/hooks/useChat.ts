import { useCallback, useRef, useState } from "react";
import {
  ChatFilters,
  ChatMessage,
  Citation,
  ConversationMessage,
  sendMessage as apiSendMessage,
  streamChatMessage,
} from "../api/client";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<ChatFilters>({});

  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;

  const cancelStreaming = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setIsStreaming(false);
    setStatusText(undefined);
    setLoading(false);
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);
      setError(null);
      setStatusText(undefined);

      // Build conversation history from ref to avoid stale closure
      const history: ConversationMessage[] = messagesRef.current.slice(-20).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Try streaming first
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        // Create placeholder assistant message
        const assistantMsg: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "", citations: [] };
        setMessages((prev) => [...prev, assistantMsg]);

        let streamingContent = "";
        const streamingCitations: Citation[] = [];
        let gotTokens = false;

        for await (const event of streamChatMessage(
          content,
          conversationId,
          history.length > 0 ? history : undefined,
          Object.keys(filters).length > 0 ? filters : undefined,
          abortController.signal
        )) {
          switch (event.type) {
            case "status":
              setStatusText(event.content);
              break;

            case "token":
              if (!gotTokens) {
                gotTokens = true;
                setIsStreaming(true);
                setStatusText(undefined);
              }
              streamingContent += event.content ?? "";
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: streamingContent,
                  };
                }
                return updated;
              });
              break;

            case "citation":
              if (event.data) {
                streamingCitations.push(event.data);
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                      ...last,
                      citations: [...streamingCitations],
                    };
                  }
                  return updated;
                });
              }
              break;

            case "done":
              if (event.conversation_id) {
                setConversationId(event.conversation_id);
              }
              if (event.metadata) {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                      ...last,
                      token_usage: event.metadata!.token_usage,
                      latency_ms: event.metadata!.latency_ms,
                    };
                  }
                  return updated;
                });
              }
              break;

            case "error":
              setError(event.message ?? "Unknown streaming error");
              // Update the assistant message with the error
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant" && !last.content) {
                  updated[updated.length - 1] = {
                    ...last,
                    content: `Error: ${event.message}`,
                  };
                }
                return updated;
              });
              break;
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // User cancelled — keep partial response
          return;
        }

        // Streaming failed — fall back to non-streaming API
        console.warn("Streaming failed, falling back to non-streaming:", err);
        // Remove the placeholder assistant message
        setMessages((prev) => prev.filter((_, i) => i !== prev.length - 1));

        try {
          const res = await apiSendMessage(
            content,
            conversationId,
            history.length > 0 ? history : undefined,
            Object.keys(filters).length > 0 ? filters : undefined
          );
          if (res.conversation_id) setConversationId(res.conversation_id);
          const assistantMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: res.response,
            citations: res.citations?.map((c) => ({
              title: c.document_title ?? "",
              document_id: c.document_title ?? "",
              source_url: c.source_url,
              segment_id: c.segment_id,
            })),
            token_usage: res.token_usage,
            latency_ms: res.latency_ms,
          };
          setMessages((prev) => [...prev, assistantMsg]);
        } catch (fallbackErr) {
          const msg = fallbackErr instanceof Error ? fallbackErr.message : "Unknown error";
          setError(msg);
          setMessages((prev) => [
            ...prev,
            { id: crypto.randomUUID(), role: "assistant", content: `Error: ${msg}` },
          ]);
        }
      } finally {
        setLoading(false);
        setIsStreaming(false);
        setStatusText(undefined);
        abortControllerRef.current = null;
      }
    },
    [conversationId, filters]
  );

  const clearChat = useCallback(() => {
    cancelStreaming();
    setMessages([]);
    setConversationId(undefined);
    setError(null);
  }, [cancelStreaming]);

  return {
    messages,
    loading,
    isStreaming,
    statusText,
    error,
    sendMessage,
    clearChat,
    cancelStreaming,
    filters,
    setFilters,
  };
}
