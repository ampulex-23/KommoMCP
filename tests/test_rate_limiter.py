"""Tests for rate limiter."""

import asyncio
import time

import pytest

from kommo_mcp.api.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_requests_under_limit():
    """Test that requests under limit are allowed immediately."""
    limiter = RateLimiter(max_requests=5, time_window=1.0)
    
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    
    # Should complete almost instantly
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_rate_limiter_throttles_over_limit():
    """Test that requests over limit are throttled."""
    limiter = RateLimiter(max_requests=3, time_window=0.5)
    
    start = time.monotonic()
    for _ in range(6):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    
    # Should take at least 0.5 seconds (one time window)
    assert elapsed >= 0.4


@pytest.mark.asyncio
async def test_rate_limiter_context_manager():
    """Test rate limiter as context manager."""
    limiter = RateLimiter(max_requests=5, time_window=1.0)
    
    async with limiter:
        pass  # Should not raise
