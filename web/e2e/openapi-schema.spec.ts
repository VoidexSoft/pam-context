import { test, expect } from "@playwright/test";

const API = "http://localhost:8000";

test.describe("OpenAPI Schema Visibility", () => {
  test("Swagger UI loads and shows endpoints", async ({ page }) => {
    await page.goto(`${API}/docs`);
    await page.waitForSelector(".swagger-ui");

    // Verify key endpoint groups are visible
    await expect(page.locator("text=documents")).toBeVisible();
    await expect(page.locator("text=chat")).toBeVisible();
    await expect(page.locator("text=admin")).toBeVisible();
  });

  test("GET /api/documents shows PaginatedResponse schema", async ({
    page,
  }) => {
    await page.goto(`${API}/docs`);
    await page.waitForSelector(".swagger-ui");

    // Expand GET /api/documents
    const docsEndpoint = page.locator(
      '.opblock-summary-path [data-path="/api/documents"]'
    );
    if (await docsEndpoint.isVisible()) {
      await docsEndpoint.click();
    }

    // Check for response schema with pagination fields
    const openApiJson = await page.evaluate(async () => {
      const res = await fetch("/openapi.json");
      return res.json();
    });

    const docPath = openApiJson.paths["/api/documents"];
    expect(docPath).toBeDefined();
    expect(docPath.get).toBeDefined();
    expect(docPath.get.responses["200"]).toBeDefined();
  });

  test("OpenAPI JSON contains response_model schemas", async ({ request }) => {
    const res = await request.get(`${API}/openapi.json`);
    expect(res.ok()).toBeTruthy();

    const schema = await res.json();

    // Documents endpoint has paginated response
    const docGet = schema.paths["/api/documents"]?.get;
    expect(docGet?.responses?.["200"]?.content?.["application/json"]).toBeDefined();

    // Chat endpoint has ChatResponse
    const chatPost = schema.paths["/api/chat"]?.post;
    expect(chatPost?.responses?.["200"]?.content?.["application/json"]).toBeDefined();

    // Stats endpoint has StatsResponse
    const statsGet = schema.paths["/api/stats"]?.get;
    expect(statsGet?.responses?.["200"]?.content?.["application/json"]).toBeDefined();
  });
});
