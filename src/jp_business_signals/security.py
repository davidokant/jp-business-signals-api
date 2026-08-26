from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from .config import Settings


class FixedWindowRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = requests_per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, identity: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        with self._lock:
            events = self._events[identity]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.requests_per_minute:
                return False
            events.append(now)
            return True


class ApiAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.limiter = FixedWindowRateLimiter(settings.rate_limit_per_minute)

    def _valid_direct_key(self, supplied: str | None) -> bool:
        if not supplied:
            return False
        return any(secrets.compare_digest(supplied, key) for key in self.settings.api_keys)

    def _valid_rapidapi_secret(self, supplied: str | None) -> bool:
        expected = self.settings.rapidapi_proxy_secret
        return bool(expected and supplied and secrets.compare_digest(supplied, expected))

    async def require_api_key(self, request: Request) -> str:
        direct_key = request.headers.get("X-API-Key")
        rapidapi_secret = request.headers.get("X-RapidAPI-Proxy-Secret")
        if self._valid_direct_key(direct_key):
            identity = f"direct:{direct_key}"
        elif self._valid_rapidapi_secret(rapidapi_secret):
            consumer = request.headers.get("X-RapidAPI-User", "unknown")
            identity = f"rapidapi:{consumer}"
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API credentials",
            )

        if not self.limiter.allow(identity):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        return identity
