from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, Request, status

from .config import UsSettings


class UsApiAuthenticator:
    def __init__(self, settings: UsSettings) -> None:
        self._settings = settings

    async def require_api_key(self, request: Request) -> str:
        supplied = request.headers.get("X-API-Key")
        if not supplied or not any(
            compare_digest(supplied, expected) for expected in self._settings.api_keys
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API credentials",
            )
        return supplied
