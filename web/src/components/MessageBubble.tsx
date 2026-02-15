import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import "katex/dist/katex.min.css";
import "../styles/code.css";

import { ChatMessage } from "../api/client";
import { processContent } from "../utils/markdown";
import { useMarkdownComponents } from "../hooks/useMarkdownComponents";
import CitationTooltip from "./chat/CitationTooltip";

interface Props {
  message: ChatMessage;
  isStreaming?: boolean;
  onViewSource?: (segmentId: string) => void;
}

function MessageBubble({ message, isStreaming, onViewSource }: Props) {
  const isUser = message.role === "user";

  const components = useMarkdownComponents({
    citations: message.citations,
    onViewSource,
  });

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-indigo-600 text-white"
            : "bg-gray-100 text-gray-800 dark:bg-zinc-800 dark:text-zinc-200"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className={`prose prose-sm max-w-none dark:prose-invert [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 ${isStreaming ? "streaming-cursor" : ""}`}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex, rehypeHighlight]}
              components={components}
            >
              {processContent(message.content)}
            </ReactMarkdown>
          </div>
        )}

        {message.citations && message.citations.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-200/30 flex flex-wrap gap-1.5">
            {message.citations.map((citation, i) => (
              <CitationTooltip
                key={i}
                citation={citation}
                index={i + 1}
                onViewSource={onViewSource}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default React.memo(MessageBubble);
