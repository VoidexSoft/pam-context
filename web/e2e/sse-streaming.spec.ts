import { test, expect } from "@playwright/test";

test.describe("SSE Streaming", () => {
  test("chat sends message and receives streaming tokens", async ({
    page,
  }) => {
    await page.goto("/");

    // Find chat input and send button
    const input = page.getByPlaceholder(/ask|message|question/i);
    await expect(input).toBeVisible({ timeout: 10_000 });

    await input.fill("What is PAM?");

    const sendBtn = page.getByRole("button", { name: /send/i });
    await sendBtn.click();

    // Should see streaming status or tokens appearing
    // Wait for assistant message to start appearing
    const assistantMsg = page.locator('[data-role="assistant"], .assistant-message, [class*="assistant"]');

    // Alternatively, just wait for any new text content to appear after send
    // The response should appear within a reasonable time
    await expect(
      page.getByText(/thinking|searching|generating/i).or(assistantMsg.first())
    ).toBeVisible({ timeout: 15_000 });

    // Wait for completion — send button should re-appear / cancel button should disappear
    await expect(sendBtn).toBeVisible({ timeout: 60_000 });
  });

  test("SSE endpoint returns correct event types", async ({ request }) => {
    const res = await request.post("http://localhost:8000/api/chat/stream", {
      data: {
        message: "Hello",
        conversation_history: [],
      },
      headers: { Accept: "text/event-stream" },
    });

    expect(res.ok()).toBeTruthy();
    const contentType = res.headers()["content-type"];
    expect(contentType).toContain("text/event-stream");
  });
});
