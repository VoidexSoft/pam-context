import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "../api/client";
import MessageBubble from "./MessageBubble";

interface Props {
  messages: ChatMessage[];
  loading: boolean;
  isStreaming?: boolean;
  statusText?: string;
  onSend: (message: string) => void;
  onCancel?: () => void;
  onViewSource?: (segmentId: string) => void;
}

export default function ChatInterface({
  messages,
  loading,
  isStreaming,
  statusText,
  onSend,
  onCancel,
  onViewSource,
}: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollHeight, scrollTop, clientHeight } = scrollRef.current;
    isAtBottomRef.current = scrollHeight - scrollTop - clientHeight <= 50;
  };

  useEffect(() => {
    if (isAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isStreaming]);

  // Auto-focus input on mount and after sending
  useEffect(() => {
    if (!loading && !isStreaming) inputRef.current?.focus();
  }, [loading, isStreaming]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading || isStreaming) return;
    setInput("");
    onSend(text);
  }

  const isBusy = loading || isStreaming;

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Messages area */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-sm">
              <div className="mx-auto w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center mb-3">
                <svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                </svg>
              </div>
              <p className="text-base font-medium text-gray-400">
                Ask anything about your business knowledge
              </p>
              <p className="text-sm text-gray-300 mt-1.5">
                PAM Context retrieves relevant documents and provides sourced answers.
              </p>
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble
            key={msg.id ?? i}
            message={msg}
            isStreaming={isStreaming && i === messages.length - 1 && msg.role === "assistant"}
            onViewSource={onViewSource}
          />
        ))}

        {/* Status text during tool execution */}
        {statusText && !isStreaming && (
          <div className="flex items-start gap-2">
            <div className="bg-gray-100 dark:bg-zinc-800 rounded-xl px-4 py-3 text-sm text-gray-500 dark:text-zinc-400">
              <span className="inline-flex items-center gap-2">
                <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse" />
                {statusText}
              </span>
            </div>
          </div>
        )}

        {/* Bouncing dots for non-streaming loading */}
        {loading && !isStreaming && !statusText && (
          <div className="flex items-start gap-2">
            <div className="bg-gray-100 dark:bg-zinc-800 rounded-xl px-4 py-3 text-sm text-gray-500">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 sm:px-6 py-3"
      >
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            aria-label="Type a message"
            className="flex-1 rounded-lg border border-gray-300 dark:border-zinc-600 bg-white dark:bg-zinc-800 px-4 py-2.5 text-sm text-gray-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            disabled={isBusy}
          />
          {isStreaming && onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              aria-label="Stop generating"
              className="px-5 py-2.5 text-sm font-medium text-white bg-red-500 rounded-lg hover:bg-red-600 transition-colors"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={isBusy || !input.trim()}
              aria-label="Send message"
              className="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Send
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
