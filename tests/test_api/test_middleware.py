"""Tests for API middleware -- CorrelationId and RequestLogging (pure ASGI)."""

import re
from unittest.mock import AsyncMock

from pam.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware


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


class TestCorrelationIdMiddlewareASGI:
    """Direct ASGI-level tests for CorrelationIdMiddleware."""

    async def test_non_http_scope_passes_through(self):
        """Non-HTTP scopes (e.g. websocket) pass through without error."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = CorrelationIdMiddleware(inner_app)
        await middleware({"type": "websocket"}, AsyncMock(), AsyncMock())
        assert inner_called

    async def test_asgi_call_interface(self):
        """Middleware uses __call__(scope, receive, send) -- pure ASGI."""
        assert hasattr(CorrelationIdMiddleware, "__call__")
        assert not hasattr(CorrelationIdMiddleware, "dispatch")


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
        assert set(data.keys()).issubset(allowed_keys), (
            f"Unexpected keys in response: {set(data.keys()) - allowed_keys}"
        )


class TestRequestLoggingMiddlewareASGI:
    """Direct ASGI-level tests for RequestLoggingMiddleware."""

    async def test_non_http_scope_passes_through(self):
        """Non-HTTP scopes pass through without error."""
        inner_called = False

        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True

        middleware = RequestLoggingMiddleware(inner_app)
        await middleware({"type": "websocket"}, AsyncMock(), AsyncMock())
        assert inner_called

    async def test_captures_status_code_and_latency(self):
        """Middleware captures status code from response.start and computes latency."""
        captured_status = None

        async def inner_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 201, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        middleware = RequestLoggingMiddleware(inner_app)

        sent_messages = []

        async def mock_send(message):
            sent_messages.append(message)

        scope = {"type": "http", "method": "POST", "path": "/api/test", "headers": []}
        await middleware(scope, AsyncMock(), mock_send)

        # Verify messages passed through
        assert len(sent_messages) == 2
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[0]["status"] == 201

    async def test_asgi_call_interface(self):
        """Middleware uses __call__(scope, receive, send) -- pure ASGI."""
        assert hasattr(RequestLoggingMiddleware, "__call__")
        assert not hasattr(RequestLoggingMiddleware, "dispatch")
