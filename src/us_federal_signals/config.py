from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class UsSettings:
    environment: str
    api_keys: frozenset[str]
    sam_api_key: str | None = None
    sam_base_url: str = "https://api.sam.gov/opportunities/v2/search"
    usaspending_base_url: str = "https://api.usaspending.gov"
    source_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> UsSettings:
        load_dotenv(override=False)
        environment = os.getenv("US_APP_ENV", "development").strip().lower()
        api_keys = frozenset(
            value.strip()
            for value in os.getenv("US_APP_API_KEYS", "dev-us-key").split(",")
            if value.strip()
        )
        if environment == "production" and "dev-us-key" in api_keys:
            raise RuntimeError("US_APP_API_KEYS must not contain dev-us-key in production")
        if not api_keys:
            raise RuntimeError("Configure US_APP_API_KEYS")
        return cls(
            environment=environment,
            api_keys=api_keys,
            sam_api_key=os.getenv("SAM_API_KEY", "").strip() or None,
            sam_base_url=os.getenv(
                "SAM_OPPORTUNITIES_BASE_URL",
                "https://api.sam.gov/opportunities/v2/search",
            ).rstrip("/"),
            usaspending_base_url=os.getenv(
                "USASPENDING_BASE_URL", "https://api.usaspending.gov"
            ).rstrip("/"),
            source_timeout_seconds=max(
                1.0, float(os.getenv("US_SOURCE_TIMEOUT_SECONDS", "30"))
            ),
        )
