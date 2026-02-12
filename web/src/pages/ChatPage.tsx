import { useState } from "react";
import ChatInterface from "../components/ChatInterface";
import SearchFilters from "../components/SearchFilters";
import SourceViewer from "../components/SourceViewer";
import { useChat } from "../hooks/useChat";

export default function ChatPage() {
  const { messages, loading, sendMessage, clearChat, filters, setFilters } = useChat();
  const [viewingSegmentId, setViewingSegmentId] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
        <h2 className="text-base font-semibold text-gray-800">Chat</h2>
        <button
          onClick={clearChat}
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          New conversation
        </button>
      </header>
      <SearchFilters filters={filters} onChange={setFilters} />
      <ChatInterface
        messages={messages}
        loading={loading}
        onSend={sendMessage}
        onViewSource={setViewingSegmentId}
      />
      <SourceViewer
        segmentId={viewingSegmentId}
        onClose={() => setViewingSegmentId(null)}
      />
    </div>
  );
}
