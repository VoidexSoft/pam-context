export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

export interface Citation {
  title: string;
  source_url?: string;
  document_id: string;
  segment_id?: string;
}

export interface ChatResponse {
  message: ChatMessage;
  conversation_id: string;
}

export interface SearchResult {
  content: string;
  score: number;
  document_id: string;
  title: string;
  source_url?: string;
}

export interface Document {
  id: string;
  title: string;
  source_type: string;
  status: string;
  last_synced_at: string | null;
  segment_count: number;
}

export interface IngestResponse {
  results: Array<{
    source_id: string;
    title: string;
    segments_created: number;
    skipped: boolean;
    error: string | null;
  }>;
  total: number;
  succeeded: number;
  skipped: number;
  failed: number;
}

const BASE = "/api";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export function sendMessage(
  message: string,
  conversationId?: string
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
}

export function searchKnowledge(query: string): Promise<SearchResult[]> {
  return request<SearchResult[]>("/search", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export function listDocuments(): Promise<Document[]> {
  return request<Document[]>("/documents");
}

export function ingestFolder(path: string): Promise<IngestResponse> {
  return request<IngestResponse>("/ingest/folder", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}
