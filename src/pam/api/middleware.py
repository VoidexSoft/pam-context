"""Pure ASGI middleware for correlation IDs and request logging.

Uses raw ASGI interface instead of BaseHTTPMiddleware to avoid
response body buffering that breaks SSE streaming.
"""

import time
from collections.abc import Callable

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pam.common.logging import set_correlation_id

logger = structlog.get_logger()


class CorrelationIdMiddleware:
    """Sets a correlation ID on each HTTP request/response via contextvars.

    Pure ASGI middleware -- passes ``send`` through directly so SSE events
    are delivered without buffering.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract X-Correlation-ID from raw ASGI headers (list of byte pairs)
        incoming_cid: str | None = None
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-correlation-id":
                incoming_cid = header_value.decode("latin-1")
                break

        cid = set_correlation_id(incoming_cid)

        async def send_with_cid(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Correlation-ID", cid)
            await send(message)

        await self.app(scope, receive, send_with_cid)


class RequestLoggingMiddleware:
    """Logs HTTP requests with method, path, status code, and latency.

    Pure ASGI middleware -- captures the status code from the response start
    message without buffering the response body.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code: int = 0

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_with_status)

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "http_request",
            method=scope["method"],
            path=scope["path"],
            status_code=status_code,
            latency_ms=round(latency_ms, 1),
        )
