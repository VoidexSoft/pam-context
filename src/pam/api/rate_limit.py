"""Rate limiting setup using slowapi."""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from pam.common.config import settings


def _key_func(request: Request) -> str:
    """Rate limit key: client IP address."""
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[settings.rate_limit_default],
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )
