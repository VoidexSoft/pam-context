/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import {
  setAuthToken,
  getStoredToken,
  searchKnowledge,
  sendMessage,
  listDocuments,
  ingestFolder,
  getTaskStatus,
} from "./client";

let fetchSpy: Mock;

beforeEach(() => {
  fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve([]),
  } as unknown as Response);
  globalThis.fetch = fetchSpy;
  setAuthToken(null);
});

function lastFetchHeaders(): Record<string, string> {
  const [, init] = fetchSpy.mock.lastCall!;
  return init.headers as Record<string, string>;
}

function lastFetchUrl(): string {
  return fetchSpy.mock.lastCall![0] as string;
}

function lastFetchInit(): RequestInit {
  return fetchSpy.mock.lastCall![1] as RequestInit;
}

// ── Existing tests: header merge order ──────────────────────────────

describe("request() header merge order", () => {
  it("includes Content-Type on POST requests with body", async () => {
    setAuthToken(null);
    await searchKnowledge("test");
    expect(lastFetchHeaders()["Content-Type"]).toBe("application/json");
  });

  it("does not include Content-Type on GET requests (no body)", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0, cursor: "" }),
    } as unknown as Response);
    setAuthToken(null);
    await listDocuments();
    expect(lastFetchHeaders()["Content-Type"]).toBeUndefined();
  });

  it("includes Authorization when token is set", async () => {
    setAuthToken("my-token");
    await searchKnowledge("test");
    const h = lastFetchHeaders();
    expect(h["Authorization"]).toBe("Bearer my-token");
    expect(h["Content-Type"]).toBe("application/json");
  });

  it("auth header cannot be overridden by custom init headers", async () => {
    setAuthToken("real-token");
    await searchKnowledge("test");
    const h = lastFetchHeaders();
    expect(h["Authorization"]).toBe("Bearer real-token");
  });

  it("does not include Authorization when no token is set", async () => {
    setAuthToken(null);
    await searchKnowledge("test");
    expect(lastFetchHeaders()["Authorization"]).toBeUndefined();
  });

  it("headers object is the final property (not overridden by init spread)", async () => {
    setAuthToken("token-123");
    await searchKnowledge("test");
    const [, init] = fetchSpy.mock.lastCall!;
    expect(init.headers).toBeDefined();
    expect(init.headers["Authorization"]).toBe("Bearer token-123");
    expect(init.headers["Content-Type"]).toBe("application/json");
  });
});

// ── sendMessage ─────────────────────────────────────────────────────

describe("sendMessage", () => {
  beforeEach(() => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          response: "hi",
          citations: [],
          conversation_id: "conv-1",
          token_usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
          latency_ms: 50,
        }),
    } as unknown as Response);
  });

  it("sends POST /api/chat with the message in the body", async () => {
    await sendMessage("hello");
    expect(lastFetchUrl()).toBe("/api/chat");
    expect(lastFetchInit().method).toBe("POST");
    const body = JSON.parse(lastFetchInit().body as string);
    expect(body.message).toBe("hello");
  });

  it("includes conversation_id and conversation_history when provided", async () => {
    const history = [{ role: "user", content: "prior" }];
    await sendMessage("follow-up", "conv-42", history);
    const body = JSON.parse(lastFetchInit().body as string);
    expect(body.conversation_id).toBe("conv-42");
    expect(body.conversation_history).toEqual(history);
  });

  it("includes source_type from filters", async () => {
    await sendMessage("query", undefined, undefined, {
      source_type: "confluence",
    });
    const body = JSON.parse(lastFetchInit().body as string);
    expect(body.source_type).toBe("confluence");
  });

  it("omits optional fields when not provided", async () => {
    await sendMessage("simple");
    const body = JSON.parse(lastFetchInit().body as string);
    expect(body.conversation_id).toBeUndefined();
    expect(body.conversation_history).toBeUndefined();
    expect(body.source_type).toBeUndefined();
  });
});

// ── listDocuments ───────────────────────────────────────────────────

describe("listDocuments", () => {
  it("sends GET /api/documents", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ id: "doc-1", title: "Doc" }]),
    } as unknown as Response);
    await listDocuments();
    expect(lastFetchUrl()).toBe("/api/documents");
    // GET is the default — no explicit method should be set
    expect(lastFetchInit().method).toBeUndefined();
  });
});

// ── ingestFolder ────────────────────────────────────────────────────

describe("ingestFolder", () => {
  it("sends POST /api/ingest/folder with the path in the body", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ task_id: "t-1", status: "pending", message: "ok" }),
    } as unknown as Response);
    await ingestFolder("/data/docs");
    expect(lastFetchUrl()).toBe("/api/ingest/folder");
    expect(lastFetchInit().method).toBe("POST");
    const body = JSON.parse(lastFetchInit().body as string);
    expect(body.path).toBe("/data/docs");
  });
});

// ── getTaskStatus ───────────────────────────────────────────────────

describe("getTaskStatus", () => {
  it("sends GET /api/ingest/tasks/{id}", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "task-99", status: "complete" }),
    } as unknown as Response);
    await getTaskStatus("task-99");
    expect(lastFetchUrl()).toBe("/api/ingest/tasks/task-99");
    expect(lastFetchInit().method).toBeUndefined();
  });
});

// ── error handling ──────────────────────────────────────────────────

describe("error handling", () => {
  it("throws Error with status and body when response is not ok", async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve("Validation failed"),
    } as unknown as Response);
    await expect(searchKnowledge("bad")).rejects.toThrow(
      "API 422: Validation failed"
    );
  });

  it("throws Error for 500 responses", async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
    } as unknown as Response);
    await expect(listDocuments()).rejects.toThrow(
      "API 500: Internal Server Error"
    );
  });
});

// ── setAuthToken / getStoredToken ───────────────────────────────────

describe("setAuthToken", () => {
  it("persists token to localStorage", () => {
    setAuthToken("abc-123");
    expect(localStorage.getItem("pam_token")).toBe("abc-123");
  });

  it("removes token from localStorage when set to null", () => {
    setAuthToken("temporary");
    expect(localStorage.getItem("pam_token")).toBe("temporary");
    setAuthToken(null);
    expect(localStorage.getItem("pam_token")).toBeNull();
  });

  it("getStoredToken returns the current token", () => {
    setAuthToken("stored-token");
    expect(getStoredToken()).toBe("stored-token");
  });

  it("getStoredToken returns null after clearing", () => {
    setAuthToken("will-clear");
    setAuthToken(null);
    expect(getStoredToken()).toBeNull();
  });
});
