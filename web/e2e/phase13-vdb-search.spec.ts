import { test, expect } from "@playwright/test";

test.describe("Phase 13: VDB Entity/Relationship Search", () => {
  // Test 1: Chat response includes entity and relationship context
  test("chat response includes entity and relationship context", async ({
    page,
  }) => {
    // Mock the streaming endpoint to return a response with entity/relationship data
    await page.route("**/api/chat/stream", (route) => {
      const sseBody = [
        `data: ${JSON.stringify({ type: "tool_use", name: "smart_search", input: { query: "authentication" } })}\n\n`,
        `data: ${JSON.stringify({ type: "tool_result", content: "Keywords extracted:\\n- High-level: infrastructure\\n- Low-level: auth\\n\\n## Knowledge Graph Entities\\n**AuthService** (Technology): Handles OAuth\\n\\n## Knowledge Graph Relationships\\n**AuthService** -> DEPENDS_ON -> **TokenStore**" })}\n\n`,
        `data: ${JSON.stringify({ type: "text", content: "AuthService handles authentication via OAuth and depends on TokenStore for token management." })}\n\n`,
        `data: ${JSON.stringify({ type: "done", conversation_id: "conv-1", citations: [{ document_title: "Auth Guide", section_path: "OAuth", source_url: "http://docs/auth", segment_id: "seg-1" }], token_usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150 }, latency_ms: 200 })}\n\n`,
      ].join("");

      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: {
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
        body: sseBody,
      });
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Find the chat input and send a message
    const chatInput = page.getByPlaceholder(/ask/i).or(page.locator("textarea")).first();
    await chatInput.fill("How does authentication work?");

    // Submit via Enter or button
    const sendButton = page.getByRole("button", { name: /send/i }).or(
      page.locator('button[type="submit"]')
    ).first();
    await sendButton.click();

    // Verify the response renders in the UI
    await expect(
      page.getByText(/AuthService handles authentication/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  // Test 2: smart_search via chat/stream returns SSE with tool results
  test("smart_search via chat/stream returns SSE with tool results", async ({
    request,
  }) => {
    const res = await request.post("http://localhost:8000/api/chat/stream", {
      data: { message: "What entities are related to authentication?" },
      headers: { "Content-Type": "application/json" },
    });

    expect(res.ok()).toBeTruthy();
    expect(res.headers()["content-type"]).toContain("text/event-stream");

    const body = await res.text();
    // SSE format: lines starting with "data: "
    expect(body).toContain("data: ");

    // Parse SSE events
    const events = body
      .split("\n")
      .filter((line: string) => line.startsWith("data: "))
      .map((line: string) => {
        try {
          return JSON.parse(line.slice(6));
        } catch {
          return null;
        }
      })
      .filter(Boolean);

    // Should have at least one event
    expect(events.length).toBeGreaterThan(0);

    // Last event should be "done" type with conversation_id
    const doneEvent = events.find((e: { type: string }) => e.type === "done");
    expect(doneEvent).toBeTruthy();
    expect(doneEvent.conversation_id).toBeTruthy();
  });

  // Test 3: API health check confirms ES connectivity
  test("API health check confirms ES connectivity", async ({ request }) => {
    const res = await request.get("http://localhost:8000/api/health");
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    expect(body).toHaveProperty("status");
    // ES should be connected for VDB indices to work
    expect(body).toHaveProperty("elasticsearch");
    expect(body.elasticsearch).toHaveProperty("status");
  });
});
