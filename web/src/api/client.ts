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

export interface SegmentDetail {
  id: string;
  content: string;
  segment_type: string;
  section_path: string | null;
  position: number;
  metadata: Record<string, unknown>;
  document_id: string;
  document_title: string | null;
  source_url: string | null;
  source_type: string | null;
}

export interface SystemStats {
  documents: {
    total: number;
    by_status: Record<string, number>;
  };
  segments: number;
  entities: {
    total: number;
    by_type: Record<string, number>;
  };
  recent_tasks: Array<{
    id: string;
    status: string;
    folder_path: string;
    total_documents: number;
    succeeded: number;
    failed: number;
    created_at: string | null;
    completed_at: string | null;
  }>;
}

export interface ChatFilters {
  source_type?: string;
}

export interface ConversationMessage {
  role: string;
  content: string;
}

export type StreamEventType = "status" | "token" | "citation" | "done" | "error";

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  data?: Citation;
  message?: string;
  metadata?: {
    conversation_id?: string;
    token_usage: Record<string, number>;
    latency_ms: number;
    tool_calls: number;
  };
}

export interface TokenResponse {
  access_token: string;
  user: AuthUser;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
}

const BASE = "/api";

let authToken: string | null = localStorage.getItem("pam_token");

export function setAuthToken(token: string | null) {
  authToken = token;
  if (token) {
    localStorage.setItem("pam_token", token);
  } else {
    localStorage.removeItem("pam_token");
  }
}

export function getStoredToken(): string | null {
  return authToken;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export function sendMessage(
  message: string,
  conversationId?: string,
  conversationHistory?: ConversationMessage[],
  filters?: ChatFilters
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      conversation_history: conversationHistory,
      source_type: filters?.source_type,
    }),
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

export function getSegment(segmentId: string): Promise<SegmentDetail> {
  return request<SegmentDetail>(`/segments/${segmentId}`);
}

export function getStats(): Promise<SystemStats> {
  return request<SystemStats>("/stats");
}

export function devLogin(email: string, name: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/dev-login", {
    method: "POST",
    body: JSON.stringify({ email, name }),
  });
}

export function getAuthStatus(): Promise<{ auth_required: boolean }> {
  return request<{ auth_required: boolean }>("/auth/status");
}

export async function getMe(): Promise<AuthUser> {
  const data = await request<{
    id: string;
    email: string;
    name: string;
  }>("/auth/me");
  return {
    id: data.id,
    email: data.email,
    name: data.name,
    role: "viewer", // Role is per-project on the backend; default for UI
  };
}

export async function* streamChatMessage(
  message: string,
  conversationId?: string,
  conversationHistory?: ConversationMessage[],
  filters?: ChatFilters,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      conversation_history: conversationHistory,
      source_type: filters?.source_type,
    }),
    signal,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(trimmed.slice(6)) as StreamEvent;
        yield event;
      } catch {
        // Skip malformed events
      }
    }
  }

  // Process remaining buffer
  if (buffer.trim().startsWith("data: ")) {
    try {
      const event = JSON.parse(buffer.trim().slice(6)) as StreamEvent;
      yield event;
    } catch {
      // Skip
    }
  }
}
