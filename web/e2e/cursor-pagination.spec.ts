import { test, expect } from "@playwright/test";

const API = "http://localhost:8000";

test.describe("Cursor Pagination", () => {
  test("GET /api/documents returns paginated envelope", async ({ request }) => {
    const res = await request.get(`${API}/api/documents?limit=2`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json();

    // Verify envelope structure
    expect(body).toHaveProperty("items");
    expect(body).toHaveProperty("total");
    expect(body).toHaveProperty("cursor");
    expect(Array.isArray(body.items)).toBe(true);
    expect(typeof body.total).toBe("number");
  });

  test("cursor enables fetching next page", async ({ request }) => {
    // First page
    const res1 = await request.get(`${API}/api/documents?limit=2`);
    const page1 = await res1.json();

    if (page1.total <= 2) {
      // Not enough docs to test pagination — cursor should be empty
      expect(page1.cursor).toBe("");
      return;
    }

    // Cursor should be non-empty when more pages exist
    expect(page1.cursor).not.toBe("");

    // Second page
    const res2 = await request.get(
      `${API}/api/documents?limit=2&cursor=${page1.cursor}`
    );
    expect(res2.ok()).toBeTruthy();
    const page2 = await res2.json();

    expect(page2.items.length).toBeGreaterThan(0);
    expect(page2.total).toBe(page1.total);

    // Items should differ between pages
    const ids1 = page1.items.map((d: { id: string }) => d.id);
    const ids2 = page2.items.map((d: { id: string }) => d.id);
    const overlap = ids1.filter((id: string) => ids2.includes(id));
    expect(overlap).toHaveLength(0);
  });

  test("documents page loads in frontend", async ({ page }) => {
    await page.goto("/documents");
    // Should see heading or table
    await expect(
      page.getByRole("heading", { name: /documents/i })
    ).toBeVisible();
  });
});
