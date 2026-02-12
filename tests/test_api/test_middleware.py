"""Tests for API middleware — CorrelationId and RequestLogging."""


class TestCorrelationIdMiddleware:
    async def test_generates_correlation_id(self, client):
        response = await client.get("/api/health")
        assert "x-correlation-id" in response.headers
        assert len(response.headers["x-correlation-id"]) > 0

    async def test_uses_provided_correlation_id(self, client):
        response = await client.get(
            "/api/health",
            headers={"X-Correlation-ID": "custom-id-123"},
        )
        assert response.headers["x-correlation-id"] == "custom-id-123"


class TestRequestLoggingMiddleware:
    async def test_request_completes(self, client):
        """RequestLoggingMiddleware should not interfere with request handling."""
        response = await client.get("/api/health")
        assert response.status_code in (200, 503)  # 503 when Redis unavailable in tests
