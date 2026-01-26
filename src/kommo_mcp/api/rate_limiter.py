"""Rate limiter for Kommo API (7 requests per second)."""

import asyncio
import time
from collections import deque
from typing import Any


class RateLimiter:
    """
    Token bucket rate limiter for Kommo API.
    
    Kommo API limit: 7 requests per second.
    """

    def __init__(self, max_requests: int = 7, time_window: float = 1.0):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window.
            time_window: Time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire permission to make a request, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            
            # Remove expired timestamps
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # If at limit, wait for oldest request to expire
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    # Remove expired after sleep
                    now = time.monotonic()
                    while self.requests and self.requests[0] <= now - self.time_window:
                        self.requests.popleft()
            
            # Record this request
            self.requests.append(time.monotonic())

    async def __aenter__(self) -> 'RateLimiter':
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        pass
