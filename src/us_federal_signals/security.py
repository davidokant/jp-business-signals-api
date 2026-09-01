from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from secrets import compare_digest

from fastapi import HTTPException, Request, status

from .config import UsSettings


class FixedWindowRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._requests_per_minute = requests_per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, identity: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        with self._lock:
            events = self._events[identity]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._requests_per_minute:
                return False
            events.append(now)
            return True


class UsApiAuthenticator:
    def __init__(self, settings: UsSettings) -> None:
        self._settings = settings
        self._limiter = FixedWindowRateLimiter(settings.rate_limit_per_minute)

    @staticmethod
    def _identity(kind: str, value: str) -> str:
        digest = hashlib.blake2s(value.encode("utf-8"), digest_size=16).hexdigest()
        return f"{kind}:{digest}"

    async def require_api_key(self, request: Request) -> str:
        direct_key = request.headers.get("X-API-Key")
        rapidapi_secret = request.headers.get("X-RapidAPI-Proxy-Secret")
        if direct_key and any(
            compare_digest(direct_key, expected) for expected in self._settings.api_keys
        ):
            identity = self._identity("direct", direct_key)
        elif (
            rapidapi_secret
            and self._settings.rapidapi_proxy_secret
            and compare_digest(rapidapi_secret, self._settings.rapidapi_proxy_secret)
        ):
            consumer = request.headers.get("X-RapidAPI-User", "unknown")
            identity = self._identity("rapidapi", consumer)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API credentials",
            )
        if not self._limiter.allow(identity):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        return identity
