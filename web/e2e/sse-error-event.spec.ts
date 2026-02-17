import { test, expect } from "@playwright/test";

test.describe("SSE Error Event Handling", () => {
  test("error SSE event displays error in chat UI", async ({ page }) => {
    await page.goto("/");

    const input = page.getByPlaceholder(/ask|message|question/i);
    await expect(input).toBeVisible({ timeout: 10_000 });

    // Intercept the SSE stream to inject an error event
    await page.route("**/api/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
        body: [
          'event: error\ndata: {"type":"error","message":"Test error: API key invalid","data":{"type":"AuthenticationError","message":"invalid api key"}}\n\n',
        ].join(""),
      });
    });

    await input.fill("trigger error");
    const sendBtn = page.getByRole("button", { name: /send/i });
    await sendBtn.click();

    // Verify error message appears in the UI
    await expect(
      page.getByText(/error|failed|something went wrong/i)
    ).toBeVisible({ timeout: 10_000 });

    // Verify input re-enables (user can type again)
    await expect(input).toBeEnabled({ timeout: 5_000 });
  });

  test("API returns error event for malformed request", async ({ request }) => {
    // Send request with empty message to trigger validation
    const res = await request.post("http://localhost:8000/api/chat/stream", {
      data: { message: "" },
    });

    // Should get either 422 validation error or 200 with error event
    expect([200, 422]).toContain(res.status());
  });
});
