"""Tests for API middleware -- CorrelationId and RequestLogging."""

import re


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

    async def test_correlation_id_format(self, client):
        """Auto-generated correlation ID is a 16-char hex string."""
        response = await client.get("/api/health")
        cid = response.headers["x-correlation-id"]
        # set_correlation_id generates uuid4().hex[:16] -- 16 hex chars
        assert re.fullmatch(r"[0-9a-f]{16}", cid), f"Unexpected correlation ID format: {cid}"


class TestRequestLoggingMiddleware:
    async def test_request_completes(self, client):
        """RequestLoggingMiddleware should not interfere with request handling."""
        response = await client.get("/api/health")
        assert response.status_code in (200, 503)  # 503 when Redis unavailable in tests

    async def test_logging_middleware_does_not_modify_response(self, client):
        """Response body from the endpoint is returned unchanged by the middleware."""
        response = await client.get("/api/health")
        data = response.json()
        # The health endpoint returns a JSON object with a "status" key at minimum
        assert "status" in data
        # Verify the middleware did not inject extra top-level keys.
        # The health endpoint returns status + service/auth info.
        allowed_keys = {"status", "services", "auth_required", "checks", "version", "uptime", "timestamp"}
        assert set(data.keys()).issubset(allowed_keys), f"Unexpected keys in response: {set(data.keys()) - allowed_keys}"
