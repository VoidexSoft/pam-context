import ReactMarkdown from "react-markdown";
import { ChatMessage } from "../api/client";
import CitationLink from "./CitationLink";

interface Props {
  message: ChatMessage;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-indigo-600 text-white"
            : "bg-gray-100 text-gray-800"
        }`}
      >
        <div className="prose prose-sm max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-200/30 flex flex-wrap gap-1.5">
            {message.citations.map((citation, i) => (
              <CitationLink key={i} citation={citation} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
