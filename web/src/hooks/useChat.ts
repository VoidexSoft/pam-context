import { useCallback, useState } from "react";
import {
  ChatFilters,
  ChatMessage,
  ConversationMessage,
  sendMessage as apiSendMessage,
} from "../api/client";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<ChatFilters>({});

  const sendMessage = useCallback(
    async (content: string) => {
      const userMsg: ChatMessage = { role: "user", content };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);
      setError(null);

      try {
        // Build conversation history from existing messages (last 20 messages)
        const history: ConversationMessage[] = messages.slice(-20).map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const res = await apiSendMessage(
          content,
          conversationId,
          history.length > 0 ? history : undefined,
          Object.keys(filters).length > 0 ? filters : undefined
        );
        setConversationId(res.conversation_id);
        setMessages((prev) => [...prev, res.message]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setError(msg);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${msg}` },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [conversationId, messages, filters]
  );

  const clearChat = useCallback(() => {
    setMessages([]);
    setConversationId(undefined);
    setError(null);
  }, []);

  return { messages, loading, error, sendMessage, clearChat, filters, setFilters };
}
