import { test, expect } from "@playwright/test";

test.describe("Phase 11: Graph Polish & Tech Debt UAT", () => {
  // Test 1: Graph Status Endpoint Includes Document Counts
  test("graph status endpoint includes document_count and graph_synced_count", async ({
    request,
  }) => {
    const res = await request.get("http://localhost:8000/api/graph/status");
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    expect(body).toHaveProperty("document_count");
    expect(body).toHaveProperty("graph_synced_count");
    expect(typeof body.document_count).toBe("number");
    expect(typeof body.graph_synced_count).toBe("number");
    // status should be present and valid
    expect(["connected", "disconnected", "unavailable"]).toContain(body.status);
  });

  // Test 2: Empty State — No Documents Ingested
  test("shows 'No documents ingested' empty state when no docs", async ({
    page,
  }) => {
    // Intercept graph status to simulate zero documents
    await page.route("**/api/graph/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "connected",
          entity_counts: {},
          total_entities: 0,
          last_sync_time: null,
          document_count: 0,
          graph_synced_count: 0,
        }),
      })
    );
    // Also intercept entities endpoint to return empty
    await page.route("**/api/graph/entities**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], next_cursor: null }),
      })
    );

    await page.goto("/graph/explore");
    await page.waitForLoadState("networkidle");

    // Should show "No documents ingested" text
    await expect(page.getByText("No documents ingested")).toBeVisible({
      timeout: 10_000,
    });

    // Should show a link/button to navigate to ingest page
    const ingestLink = page.getByRole("link", { name: /go to ingest/i });
    await expect(ingestLink).toBeVisible();
    await expect(ingestLink).toHaveAttribute("href", "/admin");

    // Verify indigo palette is used (bg-indigo-50 circle)
    const iconCircle = page.locator(".bg-indigo-50");
    await expect(iconCircle).toBeVisible();
  });

  // Test 3: Empty State — Graph Indexing In Progress
  test("shows 'Graph indexing in progress' when docs exist but no entities", async ({
    page,
  }) => {
    // Intercept graph status to simulate docs but no entities
    await page.route("**/api/graph/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "connected",
          entity_counts: {},
          total_entities: 0,
          last_sync_time: null,
          document_count: 7,
          graph_synced_count: 2,
        }),
      })
    );
    await page.route("**/api/graph/entities**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], next_cursor: null }),
      })
    );

    await page.goto("/graph/explore");
    await page.waitForLoadState("networkidle");

    // Should show "Graph indexing in progress" text
    await expect(page.getByText("Graph indexing in progress")).toBeVisible({
      timeout: 10_000,
    });

    // Should show pending count (7 - 2 = 5 documents awaiting)
    await expect(
      page.getByText(/5 documents awaiting graph indexing/)
    ).toBeVisible();

    // Verify indigo palette
    const iconCircle = page.locator(".bg-indigo-50");
    await expect(iconCircle).toBeVisible();
  });

  // Test 4: Graph Data Endpoints Return 503 When Neo4j Unavailable
  test("graph data endpoints return 503 when Neo4j unavailable", async ({
    request,
  }) => {
    // Check if Neo4j is down — this test only meaningful when Neo4j is stopped
    const statusRes = await request.get(
      "http://localhost:8000/api/graph/status"
    );
    const statusBody = await statusRes.json();

    if (statusBody.status === "connected") {
      test.skip(true, "Neo4j is connected — skipping 503 test (run after stopping Neo4j)");
      return;
    }

    // When Neo4j is stopped mid-flight, endpoints return "Graph database unavailable"
    // When graph_service is None at startup, they return "Graph service unavailable"
    const expected503Detail = /Graph (service|database) unavailable/;

    // Test neighborhood endpoint
    const neighborhoodRes = await request.get(
      "http://localhost:8000/api/graph/neighborhood/test"
    );
    expect(neighborhoodRes.status()).toBe(503);
    const neighborhoodBody = await neighborhoodRes.json();
    expect(neighborhoodBody.detail).toMatch(expected503Detail);

    // Test entities endpoint
    const entitiesRes = await request.get(
      "http://localhost:8000/api/graph/entities"
    );
    expect(entitiesRes.status()).toBe(503);
    const entitiesBody = await entitiesRes.json();
    expect(entitiesBody.detail).toMatch(expected503Detail);

    // Test history endpoint
    const historyRes = await request.get(
      "http://localhost:8000/api/graph/entity/test/history"
    );
    expect(historyRes.status()).toBe(503);
    const historyBody = await historyRes.json();
    expect(historyBody.detail).toMatch(expected503Detail);
  });
});
