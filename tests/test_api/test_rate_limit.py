"""Tests for rate limiting middleware."""

import pytest
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.util import get_remote_address

import pam.api.rate_limit as rate_limit_module
from pam.api.main import create_app


@pytest.fixture
def app_with_low_limit(monkeypatch):
    """Create app with a very low rate limit for testing."""
    low_limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["2/minute"],
    )
    monkeypatch.setattr(rate_limit_module, "limiter", low_limiter)
    app = create_app()
    # Wire the low limiter into app state
    app.state.limiter = low_limiter
    return app


@pytest.fixture
async def client(app_with_low_limit):
    transport = ASGITransport(app=app_with_low_limit, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_exceeded(client):
    """Requests exceeding the rate limit receive 429."""
    # First two requests may fail (services down) but must not be rate-limited
    for _ in range(2):
        resp = await client.get("/api/health")
        assert resp.status_code != 429

    # Third request should be rate limited
    resp = await client.get("/api/health")
    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["detail"]
