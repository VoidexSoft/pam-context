/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { setAuthToken, searchKnowledge } from "./client";

let fetchSpy: Mock;

beforeEach(() => {
  fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve([]),
  } as unknown as Response);
  globalThis.fetch = fetchSpy;
});

function lastFetchHeaders(): Record<string, string> {
  const [, init] = fetchSpy.mock.lastCall!;
  return init.headers as Record<string, string>;
}

describe("request() header merge order", () => {
  it("includes Content-Type by default", async () => {
    setAuthToken(null);
    await searchKnowledge("test");
    expect(lastFetchHeaders()["Content-Type"]).toBe("application/json");
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
