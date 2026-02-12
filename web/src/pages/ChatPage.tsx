import { useState } from "react";
import ChatInterface from "../components/ChatInterface";
import SearchFilters from "../components/SearchFilters";
import SourceViewer from "../components/SourceViewer";
import { useChat } from "../hooks/useChat";

export default function ChatPage() {
  const {
    messages,
    loading,
    isStreaming,
    statusText,
    sendMessage,
    clearChat,
    cancelStreaming,
    filters,
    setFilters,
  } = useChat();
  const [viewingSegmentId, setViewingSegmentId] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
        <h2 className="text-base font-semibold text-gray-800">Chat</h2>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 px-2.5 py-1.5 rounded-md hover:bg-gray-100 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            New conversation
          </button>
        )}
      </header>
      <SearchFilters filters={filters} onChange={setFilters} />
      <ChatInterface
        messages={messages}
        loading={loading}
        isStreaming={isStreaming}
        statusText={statusText}
        onSend={sendMessage}
        onCancel={cancelStreaming}
        onViewSource={setViewingSegmentId}
      />
      <SourceViewer
        segmentId={viewingSegmentId}
        onClose={() => setViewingSegmentId(null)}
      />
    </div>
  );
}
