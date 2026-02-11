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

export interface TaskCreatedResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface IngestionTask {
  id: string;
  status: string;
  folder_path: string;
  total_documents: number;
  processed_documents: number;
  succeeded: number;
  skipped: number;
  failed: number;
  results: Array<{
    source_id: string;
    title: string;
    segments_created: number;
    skipped: boolean;
    error: string | null;
  }>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
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

export function ingestFolder(path: string): Promise<TaskCreatedResponse> {
  return request<TaskCreatedResponse>("/ingest/folder", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function getTaskStatus(taskId: string): Promise<IngestionTask> {
  return request<IngestionTask>(`/ingest/tasks/${taskId}`);
}

export function listTasks(limit: number = 20): Promise<IngestionTask[]> {
  return request<IngestionTask[]>(`/ingest/tasks?limit=${limit}`);
}
