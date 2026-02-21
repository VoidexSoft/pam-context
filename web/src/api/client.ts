export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  token_usage?: Record<string, number>;
  latency_ms?: number;
}

export interface Citation {
  title: string;
  source_url?: string;
  document_id: string;
  segment_id?: string;
}

export interface ChatResponse {
  response: string;
  citations: Array<{
    document_title?: string;
    section_path?: string;
    source_url?: string;
    segment_id?: string;
  }>;
  conversation_id: string | null;
  token_usage: Record<string, number>;
  latency_ms: number;
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

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  cursor: string;
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
  conversation_id?: string;
  metadata?: {
    token_usage: Record<string, number>;
    latency_ms: number;
    tool_calls: number;
  };
}

export interface GraphStatus {
  status: string;
  entity_counts: Record<string, number>;
  total_entities: number;
  last_sync_time: string | null;
  error?: string;
}

export interface GraphNode {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string | null;
}

export interface GraphEdge {
  uuid: string;
  source_name: string;
  target_name: string;
  relationship_type: string;
  fact: string;
  valid_at: string | null;
  invalid_at: string | null;
}

export interface NeighborhoodResponse {
  center: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_edges: number;
}

export interface EntityListItem {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string | null;
}

export interface EntityListResponse {
  entities: EntityListItem[];
  next_cursor: string | null;
}

export interface EntityHistoryResponse {
  entity: GraphNode;
  edges: GraphEdge[];
}

export interface SyncLogEntry {
  id: string;
  document_id: string | null;
  action: string;
  segments_affected: number | null;
  details: {
    added?: Array<{ name: string; entity_type?: string }>;
    modified?: Array<{ name: string; changes?: Record<string, unknown> }>;
    removed_from_document?: Array<{ name: string }>;
    episodes_added?: number;
    episodes_removed?: number;
  };
  created_at: string;
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
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (init?.body) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
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

export async function listDocuments(): Promise<Document[]> {
  const response = await request<PaginatedResponse<Document>>("/documents");
  return response.items;
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

export function getSegment(segmentId: string): Promise<SegmentDetail> {
  return request<SegmentDetail>(`/segments/${segmentId}`);
}

export function getStats(): Promise<SystemStats> {
  return request<SystemStats>("/stats");
}

export function getGraphStatus(): Promise<GraphStatus> {
  return request<GraphStatus>("/graph/status");
}

export interface SyncGraphResult {
  synced: Array<{ doc_id: string; status: string; entities_added: number }>;
  failed: Array<{ doc_id: string; error: string }>;
  remaining: number;
}

export async function syncGraph(limit?: number): Promise<SyncGraphResult> {
  const params = limit ? `?limit=${limit}` : "";
  return request<SyncGraphResult>(`/ingest/sync-graph${params}`, {
    method: "POST",
  });
}

export function getGraphNeighborhood(entityName: string): Promise<NeighborhoodResponse> {
  return request<NeighborhoodResponse>(`/graph/neighborhood/${encodeURIComponent(entityName)}`);
}

export function getGraphEntities(params?: {
  entity_type?: string;
  limit?: number;
  cursor?: string;
}): Promise<EntityListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.entity_type) searchParams.set("entity_type", params.entity_type);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.cursor) searchParams.set("cursor", params.cursor);
  const qs = searchParams.toString();
  return request<EntityListResponse>(`/graph/entities${qs ? `?${qs}` : ""}`);
}

export function getEntityHistory(entityName: string): Promise<EntityHistoryResponse> {
  return request<EntityHistoryResponse>(`/graph/entity/${encodeURIComponent(entityName)}/history`);
}

export function getGraphSyncLogs(params?: {
  document_id?: string;
  limit?: number;
}): Promise<SyncLogEntry[]> {
  const searchParams = new URLSearchParams();
  if (params?.document_id) searchParams.set("document_id", params.document_id);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const qs = searchParams.toString();
  return request<SyncLogEntry[]>(`/graph/sync-logs${qs ? `?${qs}` : ""}`);
}

export function devLogin(email: string, name: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/dev-login", {
    method: "POST",
    body: JSON.stringify({ email, name }),
  });
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
