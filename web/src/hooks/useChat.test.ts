/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChat } from "./useChat";

// Mock the API client module
vi.mock("../api/client", () => ({
  sendMessage: vi.fn(),
  streamChatMessage: vi.fn(),
}));

import {
  sendMessage as apiSendMessage,
  streamChatMessage,
} from "../api/client";

const mockSendMessage = apiSendMessage as Mock;
const mockStreamChatMessage = streamChatMessage as Mock;

beforeEach(() => {
  vi.clearAllMocks();
});

// Helper: create an async generator from an array of StreamEvent objects
async function* makeStream(
  events: Array<{ type: string; content?: string; data?: unknown; message?: string; metadata?: unknown }>
) {
  for (const event of events) {
    yield event;
  }
}

describe("useChat", () => {
  describe("initial state", () => {
    it("has empty messages, loading false, error null", () => {
      const { result } = renderHook(() => useChat());
      expect(result.current.messages).toEqual([]);
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.isStreaming).toBe(false);
      expect(result.current.statusText).toBeUndefined();
    });
  });

  describe("sendMessage", () => {
    it("adds user message to messages", async () => {
      mockStreamChatMessage.mockReturnValue(
        makeStream([
          { type: "token", content: "Hello back" },
          { type: "done", metadata: { token_usage: {}, latency_ms: 100, tool_calls: 0 } },
        ])
      );

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("Hi there");
      });

      // First message should be from user (id is a UUID, so use toMatchObject)
      expect(result.current.messages[0]).toMatchObject({
        role: "user",
        content: "Hi there",
      });
      expect(result.current.messages[0].id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
      );
    });

    it("adds assistant message from streaming response", async () => {
      mockStreamChatMessage.mockReturnValue(
        makeStream([
          { type: "token", content: "Hello " },
          { type: "token", content: "world" },
          { type: "done", metadata: { token_usage: {}, latency_ms: 50, tool_calls: 0 } },
        ])
      );

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("test");
      });

      expect(result.current.messages).toHaveLength(2);
      expect(result.current.messages[1].role).toBe("assistant");
      expect(result.current.messages[1].content).toBe("Hello world");
    });

    it("falls back to non-streaming API when streaming fails", async () => {
      mockStreamChatMessage.mockImplementation(() => {
        // Return an async generator that throws immediately
        return (async function* () {
          throw new Error("Streaming not supported");
        })();
      });
      mockSendMessage.mockResolvedValue({
        message: { role: "assistant", content: "fallback response" },
        conversation_id: "conv-fallback",
      });

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("fallback test");
      });

      expect(mockSendMessage).toHaveBeenCalled();
      expect(result.current.messages).toHaveLength(2);
      expect(result.current.messages[1].content).toBe("fallback response");
    });

    it("sets loading to true while request is in flight", async () => {
      let resolveStream!: () => void;
      const streamPromise = new Promise<void>((r) => {
        resolveStream = r;
      });

      mockStreamChatMessage.mockImplementation(() => {
        return (async function* () {
          await streamPromise;
          yield { type: "done" as const };
        })();
      });

      const { result } = renderHook(() => useChat());

      let sendPromise: Promise<void>;
      act(() => {
        sendPromise = result.current.sendMessage("loading test");
      });

      // While waiting, loading should be true
      expect(result.current.loading).toBe(true);

      // Complete the stream
      await act(async () => {
        resolveStream();
        await sendPromise!;
      });

      expect(result.current.loading).toBe(false);
    });

    it("sets error when both streaming and fallback fail", async () => {
      mockStreamChatMessage.mockImplementation(() => {
        return (async function* () {
          throw new Error("Stream failed");
        })();
      });
      mockSendMessage.mockRejectedValue(new Error("Fallback also failed"));

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("doomed");
      });

      expect(result.current.error).toBe("Fallback also failed");
    });

    it("handles streaming error events", async () => {
      mockStreamChatMessage.mockReturnValue(
        makeStream([
          { type: "error", message: "Rate limit exceeded" },
        ])
      );

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("error test");
      });

      expect(result.current.error).toBe("Rate limit exceeded");
    });

    it("accumulates citations from streaming events", async () => {
      const citation = {
        title: "Doc A",
        document_id: "doc-1",
        source_url: "http://example.com",
      };
      mockStreamChatMessage.mockReturnValue(
        makeStream([
          { type: "token", content: "Answer" },
          { type: "citation", data: citation },
          { type: "done", metadata: { token_usage: {}, latency_ms: 50, tool_calls: 0 } },
        ])
      );

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("cite test");
      });

      expect(result.current.messages[1].citations).toEqual([citation]);
    });
  });

  describe("clearChat", () => {
    it("resets messages and error", async () => {
      mockStreamChatMessage.mockReturnValue(
        makeStream([
          { type: "token", content: "response" },
          { type: "done" },
        ])
      );

      const { result } = renderHook(() => useChat());

      await act(async () => {
        await result.current.sendMessage("will be cleared");
      });

      expect(result.current.messages.length).toBeGreaterThan(0);

      act(() => {
        result.current.clearChat();
      });

      expect(result.current.messages).toEqual([]);
      expect(result.current.error).toBeNull();
    });
  });

  describe("setFilters", () => {
    it("updates filters state", () => {
      const { result } = renderHook(() => useChat());

      expect(result.current.filters).toEqual({});

      act(() => {
        result.current.setFilters({ source_type: "confluence" });
      });

      expect(result.current.filters).toEqual({ source_type: "confluence" });
    });
  });
});
